def main(cpv):
    name = cpv.keyin("WHAT IS YOUR NAME? ")
    count = cpv.keyin("HOW MANY PARTS? ")
    f = cpv.open("PARTS", fun="OUT")
    for i in range(int(count or 0)):
        f.write(f"P{i:04d}", f"PART {i} FOR {name}")
    f.close()
    cpv.type(f"WROTE {count or 0} PARTS FOR {name or 'NOBODY'}")
