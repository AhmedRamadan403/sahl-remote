"""Local discovery and QR tests; no desktop access or external network traffic."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs,urlparse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pairing import pairing_url, normalize_code, discover_host, start_discovery, discovery_proof


class PairingTests(unittest.TestCase):
    def test_qr_fields_preserve_code_and_pin_in_fragment(self):
        uri=urlparse(pairing_url('192.168.100.8',8443,'00123456','AA:'*31+'AA'))
        self.assertFalse(uri.query)
        self.assertEqual(parse_qs(uri.fragment)['code'],['00123456'])
        self.assertEqual(parse_qs(uri.fragment)['fp'],['a'*64])

    def test_qr_rejects_public_or_malformed_target(self):
        for host in ('8.8.8.8','example.com'):
            with self.assertRaises(ValueError):pairing_url(host,8443,'12345678','a'*64)

    def test_arabic_and_persian_numbers(self):
        self.assertEqual(normalize_code('٠٠١٢ ٣٤٥٦'),'00123456')
        self.assertEqual(normalize_code('۰۰۱۲ ۳۴۵۶'),'00123456')

    def test_proof_binds_port_fingerprint_and_nonce(self):
        original=discovery_proof('00123456','a'*32,8443,'b'*64)
        self.assertNotEqual(original,discovery_proof('00123456','a'*32,8444,'b'*64))
        self.assertNotEqual(original,discovery_proof('00123456','c'*32,8443,'b'*64))
        self.assertNotEqual(original,discovery_proof('00123456','a'*32,8443,'d'*64))


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_number_finds_loopback_host_without_sending_code(self):
        transport,protocol=await start_discovery(lambda:('00123456',8443,'a'*64),host='127.0.0.1',port=0)
        try:
            result=await asyncio.to_thread(discover_host,'00123456',1,['127.0.0.1'],transport.get_extra_info('sockname')[1])
            self.assertEqual(result['host'],'127.0.0.1')
            self.assertEqual(result['fingerprint'],'a'*64)
        finally:transport.close()

    async def test_wrong_code_does_not_resolve(self):
        transport,_=await start_discovery(lambda:('00123456',8443,'a'*64),host='127.0.0.1',port=0)
        try:
            with self.assertRaises(TimeoutError):
                await asyncio.to_thread(discover_host,'99123456',.25,['127.0.0.1'],transport.get_extra_info('sockname')[1])
        finally:transport.close()

    async def test_stopped_or_busy_host_does_not_advertise(self):
        transport,_=await start_discovery(lambda:None,host='127.0.0.1',port=0)
        try:
            with self.assertRaises(TimeoutError):
                await asyncio.to_thread(discover_host,'00123456',.25,['127.0.0.1'],transport.get_extra_info('sockname')[1])
        finally:transport.close()

if __name__=='__main__':unittest.main()
