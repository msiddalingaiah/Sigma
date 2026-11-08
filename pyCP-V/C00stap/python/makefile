
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

PYTHON := C:/Users/madhu/.conda/envs/p3.13/python.exe
TELNET := C:/Windows/Sysnative/telnet.exe

# claude --resume 0645552c-da26-4b8f-9836-53c4b6a7a488
sigma:
	$(PYTHON) -m uts --disc sys.json.gz --replies 06/16/76 08:00 N -i --console  --terminals 2  --mount ../c00si/cpcp.tap --share examples

term:
	$(TELNET) localhost 2323

test:
	$(PYTHON) -m pytest

# claude --resume 54927f29-c4ed-4386-99d0-ef67b5ac0098
model:
	$(PYTHON) -m cpvmodel

modeltest:
	$(PYTHON) -m pytest cpvmodel/tests
