"""Reject Vitis AI configurations with uncalibrated convolution parameters."""
def validate_quant_config(config):
    params=config.get('param',{})
    if not params:raise ValueError('No quantized parameters in configuration')
    for name,value in params.items():
        if not isinstance(value,list) or len(value)!=2 or value[0]!=8 or not isinstance(value[1],int):
            raise ValueError('Incomplete/non-INT8 parameter quantization: '+name)
    return len(params)
