# Make an EDIT-style file: 3-byte binary keys (the line number times 1000) and
# records in EBCDIC, as EDIT keeps them (EDIT.txt:495). Then read it back in key
# order and type each line with its EDIT number.
#
# From a terminal:  MKEDIT, then  COPY POEM TO ME(K)  for PCL's numbered listing.

LINES = {
    1: "THE SIGMA HUMS IN THE MACHINE ROOM",
    2: "ITS DISCS SPIN AND ITS LIGHTS BLINK",
    3: "A USER LOGS ON AT A TELETYPE",
    5: "AND TYPES A LINE TO SEE WHAT IT WILL THINK",
}


def edit_number(key):
    """An EDIT key as EDIT shows it: the binary value / 1000, e.g. 2.500."""
    n = int.from_bytes(key, "big")
    return f"{n // 1000}.{n % 1000:03d}"


def main(cpv):
    f = cpv.open("POEM", fun="OUT", keym=3)
    for n, text in LINES.items():
        f.write(cpv.line_key(n), text.encode(cpv.EBCDIC))
    f.write((2500).to_bytes(3, "big"),               # a line between 2 and 3, as
            "(INSERTED AT 2.5)".encode(cpv.EBCDIC))  # EDIT's insert would number it
    f.close()

    for key, data in cpv.open("POEM", binary_keys=True):    # keys in byte order
        cpv.type(f"{edit_number(key):>8} {data.decode(cpv.EBCDIC)}")
    cpv.type("WROTE POEM: " + str(len(LINES) + 1) + " LINES")
