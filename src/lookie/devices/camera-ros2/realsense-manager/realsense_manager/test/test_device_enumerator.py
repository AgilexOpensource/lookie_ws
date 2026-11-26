from realsense_manager.device_enumerator import DeviceEnumerator, normalize_usb_path


SAMPLE_OUTPUT = '''
Device Name                   Serial Number       Firmware Version
Intel RealSense D405          260422273840        5.15.1.55
Device info:
    Name                          : Intel RealSense D405
    Serial Number                 : 260422273840
    Firmware Version              : 5.15.1.55
    Physical Port                 : /sys/devices/usb2/2-3/2-3.2/2-3.2:1.0/video10
    Usb Type Descriptor           : 3.2
'''


def test_parse_compact_device_output():
    records = DeviceEnumerator.parse_output(SAMPLE_OUTPUT)

    assert len(records) == 1
    assert records[0].serial_number == '260422273840'
    assert records[0].usb_path == '2-3.2'


def test_normalize_usb_path_accepts_topology_id():
    assert normalize_usb_path('2-4.2') == '2-4.2'
