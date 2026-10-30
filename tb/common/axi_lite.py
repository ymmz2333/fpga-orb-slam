"""Small dependency-free AXI4-Lite master for cocotb HLS tests."""
from cocotb.triggers import RisingEdge


def signal(dut, name):
    for candidate in (name, name.lower(), name.upper()):
        try:
            return getattr(dut, candidate)
        except AttributeError:
            pass
    raise AttributeError("DUT signal not found: {}".format(name))


def drive_axi_sidebands(dut, prefix):
    for suffix in ("RID", "RUSER", "BID", "BUSER"):
        signal(dut, prefix + "_" + suffix).value = 0


class AxiLiteMaster:
    def __init__(self, dut, prefix, clock):
        self.clock = clock
        for suffix in (
            "AWVALID", "AWREADY", "AWADDR", "WVALID", "WREADY",
            "WDATA", "WSTRB", "BVALID", "BREADY", "BRESP",
            "ARVALID", "ARREADY", "ARADDR", "RVALID", "RREADY",
            "RDATA", "RRESP",
        ):
            setattr(self, suffix.lower(), signal(dut, prefix + "_" + suffix))
        self.awvalid.value = 0
        self.awaddr.value = 0
        self.wvalid.value = 0
        self.wdata.value = 0
        self.wstrb.value = 0
        self.bready.value = 1
        self.arvalid.value = 0
        self.araddr.value = 0
        self.rready.value = 1

    async def write(self, address, data, strobe=0xF, timeout_cycles=100):
        self.awaddr.value = address
        self.awvalid.value = 1
        self.wdata.value = data
        self.wstrb.value = strobe
        self.wvalid.value = 1
        address_done = False
        data_done = False
        for _ in range(timeout_cycles):
            await RisingEdge(self.clock)
            if not address_done and int(self.awready.value):
                address_done = True
                self.awvalid.value = 0
            if not data_done and int(self.wready.value):
                data_done = True
                self.wvalid.value = 0
            if address_done and data_done:
                break
        else:
            raise TimeoutError("AXI-Lite write address/data handshake timed out")
        for _ in range(timeout_cycles):
            await RisingEdge(self.clock)
            if int(self.bvalid.value):
                response = int(self.bresp.value)
                assert response == 0, "AXI-Lite write BRESP={}".format(response)
                return
        raise TimeoutError("AXI-Lite write response timed out")

    async def read(self, address, timeout_cycles=100):
        self.araddr.value = address
        self.arvalid.value = 1
        for _ in range(timeout_cycles):
            await RisingEdge(self.clock)
            if int(self.arready.value):
                self.arvalid.value = 0
                break
        else:
            raise TimeoutError("AXI-Lite read address handshake timed out")
        for _ in range(timeout_cycles):
            await RisingEdge(self.clock)
            if int(self.rvalid.value):
                response = int(self.rresp.value)
                value = int(self.rdata.value)
                assert response == 0, "AXI-Lite read RRESP={}".format(response)
                return value
        raise TimeoutError("AXI-Lite read response timed out")
