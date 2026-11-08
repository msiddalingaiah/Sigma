
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

PYTHON := C:/Users/madhu/.conda/envs/p3.13/python.exe
TELNET := C:/Windows/Sysnative/telnet.exe

sigma:
	$(PYTHON) -m uts --disc sys.json.gz --replies 06/16/76 08:00 N -i --console  --terminals 2  --mount ../c00si/cpcp.tap --share examples

term:
	$(TELNET) localhost 2323

test:
	$(PYTHON) -m pytest

modeltest:
	$(PYTHON) -m pytest cpvmodel/tests

model:
	$(PYTHON) -m cpvmodel
