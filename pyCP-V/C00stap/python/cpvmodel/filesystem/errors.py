"""File errors, as a program sees them."""

from ..glossary import modelOnly

NO_SUCH_FILE = 0x03             # as FIX1 handles it; OPEN's own codes weren't read
END_OF_FILE = 0x06
NO_KEY = 0x17                   # a keyed write with no key
WRONG_MODE = 0x15               # an operation error
KEY_NOT_FOUND = 0x43            # KEYER3
DISC_FULL = 0x00                # the code CP-V uses wasn't traced
ACCESS_REFUSED = 0x14           # OPENER03
BEYOND_END = 0x42               # a random file's granule number past the end (ERR01)
SHORT_TRANSFER = 0x44           # a random transfer cut short by the end (E5744)


@modelOnly("CP-V reports file errors with a code in the DCB and goes to the program's error "
           "address, or aborts it; the model throws this into the program")
class FileError(Exception):
    def __init__(self, code, message):
        super().__init__(f"X'{code:02X}': {message}")
        self.code = code
