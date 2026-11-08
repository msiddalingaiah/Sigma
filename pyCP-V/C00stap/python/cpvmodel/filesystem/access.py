"""Who may open a file: its protection, and OPEN's check."""

from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from .errors import ACCESS_REFUSED, FileError

ALL = "ALL"
NONE = "NONE"
PRIVILEGED = 0xC0               # privilege that opens anything, and creates files anywhere
SYSTEM_ACCOUNT = ":SYS"


@cpv("FIL9", "FIL3", source="CLS.txt:2288-2335",
     note="CLOSE copies these from the DCB's VLPs into a new file's FIT")
@dataclass(frozen=True)
class Protection:
    """Who may open a file. An account list holds accounts, or ``ALL`` or ``NONE``.

    - ``password``: None for none. An empty password lets only the ``:SYS`` account in.
    - ``writeAccounts`` may open the file for anything, as its owner may.
    - ``readAccounts`` may open it IN.
    - ``executeAccounts`` may run it, through a processor (the execute vehicle); the model
      doesn't have processors, so execute access is refused.

    A file with no read and no execute accounts may be read by anyone.
    """
    password: str = None
    readAccounts: tuple = ()
    writeAccounts: tuple = ()
    executeAccounts: tuple = ()

    cpvNames = {
        "password": cpv("SECCHK0", "SECCHK05", source="OBSE.txt:316-334", note="VLP X'03'"),
        "readAccounts": cpv("SEC0", source="OBSE.txt:358-367", note="VLP X'05'"),
        "writeAccounts": cpv("SECCHK2", "SECCHK3", source="OBSE.txt:342-357", note="VLP X'06'"),
        "executeAccounts": cpv("SEC0", "SEC99", source="OBSE.txt:365-394",
                               note="VLP X'14', with the execute vehicle in X'15'"),
    }


@cpv("SECCHK", "OPENER03", source="OBSE.txt:212-213, OBSE.txt:310-409",
     note="CHECK SECURITY: a refusal is code X'14'")
class AccessCheck:
    """OPEN's check, in CP-V's order:

    1. Privilege X'C0' or more opens anything.
    2. A password must match. An empty one lets only the ``:SYS`` account in, as its own.
    3. The owner opens the file for anything.
    4. A write account (or ``ALL``) opens it for anything, as if it were the user's own.
    5. Otherwise only IN: a file with no read or execute accounts is open to anyone; a read
       account (or ``ALL``) may read it.
    6. Execute accounts would give access through a processor; the model refuses.

    ``check`` returns whether the user may treat the file as their own (the DCB's ``USR``
    bit clear), which matters for deleting it.
    """

    cpvNames = {}

    @cpv("SECCHK", "SECCHK1", "SECCHK4", source="OBSE.txt:310-409")
    def check(self, user, header, readOnly, password=None):
        """Raise X'14' if ``user`` may not open the file (``readOnly``: opened IN)."""
        protection = header.protection
        own = header.account == user.account
        if user.privilege >= PRIVILEGED:
            return own
        if protection.password is not None:
            if protection.password == "":
                if user.account != SYSTEM_ACCOUNT:
                    self.refuse(header, "it is for :SYS only")
                return True
            if password != protection.password:
                self.refuse(header, "wrong password")
        if own or self.listed(user, protection.writeAccounts):
            return True
        if not readOnly:
            self.refuse(header, "it may only be read")
        if not protection.readAccounts and not protection.executeAccounts:
            return False
        if self.listed(user, protection.readAccounts):
            return False
        self.refuse(header, "no read access")

    @cpv("CLM", "SECCHK2B", source="OBSE.txt:344-357",
         note="CLM compares an entry with NONE and ALL at once")
    def listed(self, user, accounts):
        return ALL in accounts or user.account in accounts

    @cpv("OPENER03", "CLRFIB", source="OBSE.txt:212-213, OBSE.txt:415")
    def refuse(self, header, why):
        raise FileError(ACCESS_REFUSED, f"{header.account} {header.name}: {why}")

    @cpv("OP71", "JB:PRIV", source="OPNF.txt:1319-1325",
         note="ALLOW C0 PRIV TO CREATE FILES IN OTHERS ACCOUNT")
    def checkCreate(self, user, account, name):
        if account != user.account and user.privilege < PRIVILEGED:
            raise FileError(ACCESS_REFUSED,
                            f"{account} {name}: creating a file in another account")

    @modelOnly("Whether the user may delete a file they have open IN (CLSFIL, CLS.txt:1528)")
    def mayDelete(self, user, handle):
        return handle.ownFile or user.privilege >= PRIVILEGED
