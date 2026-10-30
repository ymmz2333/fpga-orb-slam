"""Computer/PS video policy. No flight commands."""
DEFAULT_BITRATE = 4


def video_settings(bitrate=DEFAULT_BITRATE):
    if type(bitrate) is not int or not 0 <= bitrate <= 5:
        raise ValueError('Bitrate must be 0 (auto) or 1..5 Mbps')
    return ('setresolution high',f'setbitrate {bitrate}','setfps high')
