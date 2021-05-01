"""Hypervisor module"""
import logging
import collections
import xml.etree.ElementTree as ET
import uuid
import time
import ipaddress
import libvirt
from randmac import RandMac


class Hypervisor:

    def __init__(self, uri, pool):
        try:
            self.conn = libvirt.open(uri)
        except libvirt.libvirtError as e:
            logging.error('Failed to open connection to the hypervisor: {}'.format(e))
            raise

        # v = self.conn.getVersion()
        # logging.info('libvirt version: {}.{}.{}'.format(v//1000000, (v //1000) % 1000, v %1000))
        # v = self.conn.getLibVersion()
        # logging.info('Host libvirt version: {}.{}.{}'.format(v//1000000, (v //1000) % 1000, v %1000))

        # set the active storage pool
        self.sp = self.conn.storagePoolLookupByName(pool)

    def __del__(self):
        if(self.conn):
            self.conn.close()

    def get_vms(self):
        VMId = collections.namedtuple('VMId', ['ID', 'Name', 'UUID'])
        domains = self.conn.listAllDomains()
        return [VMId(d.ID(), d.name(), d.UUIDString()) for d in domains]

    def get_vm(self, name):
        return self.conn.lookupByName(name)

    def get_vm_by_id(self, id):
        return self.conn.lookupByID(id)

    def create_volume_with_backing(self, name, backing_store):
        template = """
            <volume type='file'>
                <name></name>
                <allocation>0</allocation>
                <capacity></capacity>
                <target>
                    <format type='qcow2'/>
                </target>
                <backingStore>
                    <path></path>
                    <format type='qcow2'/>
                </backingStore>
            </volume>"""
        tree = ET.fromstring(template)

        # Get backing store volume info
        backingVol = self.conn.storageVolLookupByPath(backing_store)
        backingCapacity = backingVol.info()[1]

        # Set the name
        tree.find('./name').text = '{}.qcow2'.format(name)
        # Set the size
        tree.find('./capacity').text = str(backingCapacity)
        # Set the backing store
        tree.find('./backingStore/path').text = backing_store
        # store the new description
        volume_xml = ET.tostring(tree, encoding='utf-8').decode(encoding='utf-8')
        return self.sp.createXML(volume_xml)

    def create_temp_vm(self, src_name, dst_name):
        src = self.get_vm(src_name)
        src_xml = src.XMLDesc(libvirt.VIR_DOMAIN_XML_SECURE | libvirt.VIR_DOMAIN_XML_INACTIVE)
        dst_xml = ET.fromstring(src_xml)
        # Create new UUID
        dst_xml.find('./uuid').text = str(uuid.uuid4())
        # Set the new name
        dst_xml.find('./name').text = dst_name

        # update the volume
        src_volume = dst_xml.find('./devices/disk[@device=\'disk\']/source').attrib['file']
        # Create the new volume
        dst_volume = self.create_volume_with_backing(dst_name, src_volume)
        # Set the new volume
        dst_xml.find('./devices/disk[@device=\'disk\']/source').attrib['file'] = dst_volume.path()

        # Update the mac
        dst_xml.find('./devices/interface[@type=\'network\']/mac').attrib['address'] = str(RandMac())

        # store the new description
        dst_xml_str = ET.tostring(dst_xml, encoding='utf-8').decode(encoding='utf-8')
        return self.conn.defineXML(dst_xml_str)

    def delete_temp_vm(self, name):
        d = self.get_vm(name)
        d.undefine()

        v = self.sp.storageVolLookupByName('{}.qcow2'.format(name))
        v.wipe()
        v.delete()

    def get_ip_from_vm(self, vm):
        interfaces = vm.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT)
        validIps = []
        for interface in interfaces:
            val = interfaces[interface]
            if val['addrs'] and val['hwaddr']:
                for ipaddr in val['addrs']:
                    addr = ipaddr['addr']
                    if ipaddr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4 and ipaddress.ip_address(addr).is_private and not ipaddress.ip_address(addr).is_link_local:
                        validIps.append(addr)

        return validIps[0] if len(validIps) > 0 else None

    def wait_until_vm_has_ip(self, vm, timeout=30):
        for _ in range(timeout):
            try:
                ip = self.get_ip_from_vm(vm)
                if ip:
                    return ip
            except libvirt.libvirtError:
                pass
            time.sleep(1)
        raise TimeoutError
