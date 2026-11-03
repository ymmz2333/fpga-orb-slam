from types import SimpleNamespace
import numpy as np
import pytest
from orb60.dense.kv260.common import preprocess
from orb60.dense.kv260.fastdepth.bridge import to_native,to_inverse,dpu_forward


def test_rgb_boundary_keeps_color_and_native_shape():
    x=preprocess(np.full((21,31,3),(255,0,0),np.uint8))
    native=to_native(x)
    assert native.shape==(1,3,224,224) and native.dtype==np.float32
    np.testing.assert_allclose(native[0,:,100,100],[1,0,0],atol=1e-6)
    with pytest.raises(ValueError):to_native(np.full((1,3,256,256),np.nan,np.float32))


def test_depth_inverse_rejects_invalid_regions():
    depth=np.full((224,224),2.,np.float32);depth[80:120,80:120]=0
    result=to_inverse(depth)
    assert result.shape==(256,256) and result[0,0]==.5 and result[110,110]==0
    with pytest.raises(ValueError):to_inverse(np.full((224,224),np.nan,np.float32))


class Buffer:
    def __init__(self,shape,value,fix):self.array=np.full(shape,value,np.int8);self.fix=fix
    def __array__(self,dtype=None):return self.array.astype(dtype) if dtype else self.array
    def get_tensor(self):return self
    def get_attr(self,name):return self.fix


def test_dpu_boundary_adapter_without_claiming_hardware():
    inputs=[Buffer((1,224,224,3),0,6)];outputs=[Buffer((1,224,224,1),64,5)]
    runner=SimpleNamespace(execute_async=lambda i,o:1,wait=lambda j:0)
    engine=SimpleNamespace(inputs=inputs,outputs=outputs,runner=runner)
    x=preprocess(np.full((256,256,3),255,np.uint8));result=dpu_forward(engine,x)
    np.testing.assert_allclose(result,.5)
    assert inputs[0].array[0,0,0,0]==64
