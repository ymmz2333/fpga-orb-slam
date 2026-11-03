"""Equivalent inference graph with explicit modules required by the vendor QAT API."""
import types
import copy
import torch
from pytorch_nndct.nn import QuantStub,DeQuantStub
from pytorch_nndct.nn.modules.functional import Add,Pad,Interpolate


class BoundPad(torch.nn.Module):
    def __init__(self,padding):
        super().__init__();self.operation=Pad();self.padding=padding
    def forward(self,value):return self.operation(value,self.padding,'constant',0)


class FloatAdd(torch.nn.Module):
    def __init__(self):super().__init__();self.operation=Add()
    def add(self,x,y):return self.operation(x,y)


def inverted(self,x):
    residual=x;x=self.act1(self.bn1(self.conv_pw(x)));x=self.act2(self.bn2(self.conv_dw(x)))
    x=self.bn3(self.conv_pwl(self.se(x)))
    return self.quant_add(x,residual) if self.has_residual else x


def depthwise(self,x):
    residual=x;x=self.act1(self.bn1(self.conv_dw(x)));x=self.act2(self.bn2(self.conv_pw(self.se(x))))
    return self.quant_add(x,residual) if self.has_residual else x


def fusion(self,*xs):
    output=xs[0]
    if len(xs)==2:output=self.skip_add.add(output,self.resConfUnit1(xs[1]))
    output=self.resConfUnit2(output)
    return self.out_conv(self.quant_interpolate(output,scale_factor=2,mode='bilinear',align_corners=self.align_corners))


def interpolate(self,x):return self.quant_interpolate(x,scale_factor=self.scale_factor,mode=self.mode,align_corners=False)


def residual(self,x):
    out=self.conv1(self.quant_activation1(x))
    if self.bn:out=self.bn1(out)
    out=self.conv2(self.quant_activation2(out))
    if self.bn:out=self.bn2(out)
    if self.groups>1:out=self.conv_merge(out)
    return self.skip_add.add(out,x)


class Scoped(torch.nn.Module):
    def __init__(self,net):
        super().__init__();self.quant=QuantStub();self.net=net;self.dequant=DeQuantStub()
    def forward(self,x):return self.dequant(self.net(self.quant(x)))


def prepare(model):
    for name,layer in list(model.named_modules()):
        if type(layer).__name__=='Conv2dSameExport':
            conv=torch.nn.Conv2d(layer.in_channels,layer.out_channels,layer.kernel_size,layer.stride,layer.padding,
                                 layer.dilation,layer.groups,layer.bias is not None)
            conv.weight=layer.weight;conv.bias=layer.bias
            parent=model;parts=name.split('.')
            for part in parts[:-1]:parent=getattr(parent,part)
            setattr(parent,parts[-1],torch.nn.Sequential(BoundPad(layer.pad.padding),conv))
    for name,layer in list(model.named_modules()):
        cls=type(layer).__name__
        if cls=='FloatFunctional':
            parent=model;parts=name.split('.')
            for part in parts[:-1]:parent=getattr(parent,part)
            setattr(parent,parts[-1],FloatAdd())
        if cls in ['InvertedResidual','DepthwiseSeparableConv']:
            layer.quant_add=Add();layer.forward=types.MethodType(inverted if cls=='InvertedResidual' else depthwise,layer)
        if cls in ['FeatureFusionBlock_custom','Interpolate']:
            layer.quant_interpolate=Interpolate();layer.forward=types.MethodType(fusion if cls=='FeatureFusionBlock_custom' else interpolate,layer)
        if cls=='ResidualConvUnit_custom':
            layer.quant_activation1=copy.deepcopy(layer.activation);layer.quant_activation2=copy.deepcopy(layer.activation)
            layer.forward=types.MethodType(residual,layer)
    return Scoped(model).eval()
