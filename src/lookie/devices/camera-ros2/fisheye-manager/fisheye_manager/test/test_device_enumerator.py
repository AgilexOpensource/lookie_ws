from fisheye_manager.device_enumerator import (
    DeviceEnumerator,
    is_fisheye_camera,
    normalize_usb_path,
    parse_id_path,
    video_index,
)


def test_parse_id_path_matches_driver_format():
    assert parse_id_path('pci-0000:00:14.0-usb-0:10.1:1.0') == '1-10.1:1.0'
    assert parse_id_path('not-a-usb-path') is None


def test_normalize_usb_path_accepts_short_and_id_path():
    assert normalize_usb_path('1-10.1:1.0') == '1-10.1:1.0'
    assert normalize_usb_path('pci-0000:00:14.0-usb-0:8.1:1.0') == '1-8.1:1.0'
    assert normalize_usb_path('  ') == ''


def test_video_index_sorts_numerically():
    assert video_index('/dev/video2') < video_index('/dev/video10')
    assert video_index('/dev/video8') == 8


def test_is_fisheye_camera_filters_non_decxin():
    assert is_fisheye_camera('DECXIN  CAMERA: DECXIN  CAMERA', '1bcf', '2cd1')
    assert is_fisheye_camera('DECXIN CAMERA: DECXIN CAMERA', '1bcf', '2cd1')
    assert not is_fisheye_camera('Other Camera', '1bcf', '2cd1')


def test_parse_properties_accepts_decxin_capture_device():
    record = DeviceEnumerator.parse_properties('/dev/video8', {
        'ID_V4L_CAPABILITIES': ':capture:',
        'ID_V4L_PRODUCT': 'DECXIN  CAMERA: DECXIN  CAMERA',
        'ID_VENDOR_ID': '1bcf',
        'ID_MODEL_ID': '2cd1',
        'ID_VENDOR': 'DECXIN_CAMERA',
        'ID_PATH': 'pci-0000:00:14.0-usb-0:10.1:1.0',
        'ID_SERIAL_SHORT': '01.00.00',
    })
    assert record is not None
    assert record.usb_path == '1-10.1:1.0'
    assert record.vid_pid == '1bcf:2cd1'
    assert record.video_device == '/dev/video8'


def test_parse_properties_accepts_single_space_product_name():
    record = DeviceEnumerator.parse_properties('/dev/video8', {
        'ID_V4L_CAPABILITIES': ':capture:',
        'ID_V4L_PRODUCT': 'DECXIN CAMERA: DECXIN CAMERA',
        'ID_VENDOR_ID': '1bcf',
        'ID_MODEL_ID': '2cd1',
        'ID_VENDOR': 'DECXIN',
        'ID_PATH': 'pci-0000:00:14.0-usb-0:9.1:1.0',
        'ID_SERIAL_SHORT': '01.00.00',
    })
    assert record is not None
    assert record.usb_path == '1-9.1:1.0'
    assert record.product == 'DECXIN CAMERA: DECXIN CAMERA'


def test_parse_properties_rejects_non_capture_or_other_product():
    assert DeviceEnumerator.parse_properties('/dev/video0', {
        'ID_V4L_CAPABILITIES': ':capture:',
        'ID_V4L_PRODUCT': 'Other',
        'ID_VENDOR_ID': '8086',
        'ID_MODEL_ID': '0b5b',
        'ID_PATH': 'pci-0000:00:14.0-usb-0:7.2:1.0',
    }) is None
