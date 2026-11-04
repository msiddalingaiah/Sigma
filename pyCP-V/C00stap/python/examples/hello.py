def main(cpv):
    cpv.type("HELLO OPERATOR, IT IS " + cpv.time())
    f = cpv.open("PARTS", fun="OUT")
    for i in range(5):
        f.write(f"P{i:04d}", f"PART {i}")
    f.close()
    cpv.wait(1)
    for key, data in cpv.open("PARTS"):
        cpv.type(key + " = " + data.decode())
    try:
        cpv.open("PARTS").read("NOPE")
    except cpv.CpvError as e:
        cpv.type(f"NO SUCH KEY: CODE {e.code:02X}")
