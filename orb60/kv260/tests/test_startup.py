import configparser
from pathlib import Path
import hashlib
import pytest
from orb60.kv260.startup.install import automatic_login
from orb60.kv260.startup.boot_platform import checked_paths,refreshed_config


def test_autologin_keeps_other_gdm_sections_and_overrides_disabled_values():
    original='[daemon]\n# keep me\nWaylandEnable=false\nAutomaticLoginEnable=false\nAutomaticLogin=someone\n[security]\nDisallowTCP=true\n'
    text=automatic_login(original,'ubuntu');parser=configparser.ConfigParser();parser.read_string(text)
    assert parser['daemon']['AutomaticLoginEnable']=='true' and parser['daemon']['AutomaticLogin']=='ubuntu'
    assert parser['daemon']['WaylandEnable']=='false' and parser['security']['DisallowTCP']=='true' and '# keep me' in text
    assert automatic_login(text,'ubuntu')==text


def test_autologin_handles_commented_defaults_without_enabling_other_login_modes():
    text=automatic_login('[daemon]\n# AutomaticLogin = user1\n[debug]\nEnable=false\n','ubuntu')
    parser=configparser.ConfigParser();parser.read_string(text)
    assert parser['daemon']['AutomaticLogin']=='ubuntu' and parser['debug']['Enable']=='false'
    with pytest.raises(ValueError):automatic_login(text,'root\n[security]')


def test_changed_or_escaped_boot_asset_is_rejected_before_any_hardware_command(tmp_path):
    file=tmp_path/'firmware';file.write_bytes(b'approved firmware')
    config=dict(paths={'firmware':'firmware'},sha256={'firmware':hashlib.sha256(file.read_bytes()).hexdigest()})
    assert checked_paths(tmp_path,config)['firmware']==file
    file.write_bytes(b'changed')
    with pytest.raises(ValueError):checked_paths(tmp_path,config)
    config['paths']['firmware']='../outside'
    with pytest.raises(ValueError):checked_paths(tmp_path,config)


def test_new_boot_receipts_do_not_change_camera_model_map_or_frontend_selection(tmp_path):
    before=dict(camera='calibration.csv',model='same.xmodel',endpoint='same-7015',native_build='same-native',point_uio='/dev/uio4')
    result=refreshed_config(before,tmp_path,tmp_path/'startup_runtime'/'new-boot','/dev/uio5')
    assert all(result[k]==before[k] for k in ('camera','model','endpoint','native_build'))
    assert result['point_uio']=='/dev/uio5' and 'new-boot' in result['deployment_receipt']
