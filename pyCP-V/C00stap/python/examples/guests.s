*
*  GUESTS - a visitors' book in Sigma machine code, for the interpreter
*  (docs/interpreter.md). Asks the operator's name (M:KEYIN), appends it to
*  the consecutive file VISITORS through its own DCB (docs/dcb.md), then
*  types every name in the book. Run it with a disc image to keep the book:
*
*     python -m uts --disc book.json.gz --replies 06/15/76 13:45 N
*                   --file examples/guests.s=GUESTS --keyins "GJOB GUESTS" ADA
*
         ORG      X'D000'
START    CAL1,2   ASK               M:KEYIN: the reply is a TEXTC in BUF
         LB,3     BUF
         AI,3     1                 the record: the count byte and the name
         STW,3    WSIZE
         CAL1,1   OPEN              UPDATE: the book, if there is one
SKIP     CAL1,1   READ              to the end of the file ...
         BCR,0    SKIP
APPEND   CAL1,1   WRITE             ... where the write appends
         CAL1,1   CLOSE
         LW,4     FUNIN             FUN = IN, in the DCB itself
         STW,4    F:VIS+1
         CAL1,1   OPEN
         CAL1,2   TYPEHDR
LIST     CAL1,1   READ2
         CAL1,2   TYPE              each record is a TEXTC
         BCR,0    LIST
DONE     CAL1,1   CLOSE
         CAL1,9   1                 M:EXIT
ERR      CAL1,2   TYPEERR
         CAL1,9   3                 M:XXX
NEW      LW,4     FUNOUT            no book yet (abnormal X'03'): FUN = OUT
         STW,4    F:VIS+1
         CAL1,1   OPEN              ... which creates it
         BCR,0    APPEND
*
*  FPTs: code and DCB, the presence bits, then the parameters
*
ASK      DATA     X'04000000',X'E0000000',QUESTION,BUF,40
OPEN     DATA     X'14000000'+F:VIS,X'C0000000',ERR,NEW
CLOSE    DATA     X'15000000'+F:VIS,0
READ     DATA     X'10000000'+F:VIS,X'F0000000',ERR,APPEND,INBUF,64
READ2    DATA     X'10000000'+F:VIS,X'F0000000',ERR,DONE,INBUF,64
WRITE    DATA     X'11000000'+F:VIS,X'F0000000',ERR,ERR,BUF
WSIZE    DATA     0
TYPE     DATA     X'02000000',X'80000000',INBUF
TYPEHDR  DATA     X'02000000',X'80000000',HDR
TYPEERR  DATA     X'02000000',X'80000000',MERR
FUNIN    DATA     X'00020000'
FUNOUT   DATA     X'00040000'
QUESTION TEXTC    'WHAT IS YOUR NAME?'
HDR      TEXTC    'THE VISITORS SO FAR:'
MERR     TEXTC    'GUESTS: FILE ERROR'
BUF      RES      12
INBUF    RES      17
*
*  The DCB: 22 words, then its one VLP, the file name
*
F:VIS    DATA     X'1F000001'       its size; ASN 1, a file
         DATA     X'00080000'       FUN = UPDATE
         DATA     X'03000000'       3 retries
         DATA     0,0
         DATA     0                 ORG 0: consecutive
         DATA     VLPS              FLP: the VLP list
         RES      15
VLPS     DATA     X'01010308'       code 1, last, 3 words used, 8 reserved
         TEXTC    'VISITORS'
         RES      5
         END      START
