*
*  HELLO - a first AP program. Types a greeting, counts down from 3,
*  and exits. To assemble it at a terminal (docs/online.md, docs/assign.md):
*
*     python -m uts --disc sys.json.gz --replies 06/16/76 08:00 N -i --console  --terminals 2  --mount ../c00si/cpcp.tap --share examples
*
*     !TAPE CPCO AP $:STDDEF          (once: AP into your account)
*     !IMPORT hello.asm               (this file, as HELLO)
*     !AP HELLO OVER HELLOBO,HELLOLS  (source, object, listing)
*     >                               (AP asks OPTIONS: just Enter)
*     !EXPORT HELLOLS TO hello.lst    (the listing, back to the host)
*
*  Columns as on a card: label 1, operation 10, operands 19. Tabs work
*  too: IMPORT puts them at those columns.
*
         DEF      START
COUNT    EQU      3                 how far to count
*
START    CAL1,2   TYPEHI            M:TYPE: the greeting
         LI,5     COUNT
LOOP     LW,7     5                 the count as an EBCDIC digit ...
         AI,7     X'F0'
         LW,6     MSGN+1            ... into the message's last byte
         AND,6    MASK
         OR,6     7
         STW,6    MSGN+1
         CAL1,2   TYPEN
         BDR,5    LOOP              3, 2, 1
         CAL1,2   TYPEBYE
         CAL1,9   1                 M:EXIT
*
*  M:TYPE FPTs: the code, the presence bit, the message (a TEXTC)
*
TYPEHI   DATA     X'02000000',X'80000000',HI
TYPEN    DATA     X'02000000',X'80000000',MSGN
TYPEBYE  DATA     X'02000000',X'80000000',BYE
MASK     DATA     X'FFFFFF00'
HI       TEXTC    'HELLO FROM AP'
MSGN     TEXTC    'COUNT X'         the X is replaced by the digit
BYE      TEXTC    'GOODBYE'
         END      START
