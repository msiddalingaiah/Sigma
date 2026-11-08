*
*  CALC - a small interpreter in AP: integer expressions, variables A-Z.
*
*     >A = 6*7              assign
*     >PRINT (A - 2) / 4    print (PRINT may be left out)
*     >BYE                  end
*
*  + - * / with the usual precedence, parentheses, unary minus. Errors:
*  SYNTAX ERROR, DIVISION BY ZERO. To build and run it (docs/online.md):
*
*     !IMPORT calc.asm
*     !AP CALC OVER CALCBO,CALCLS     (Enter at OPTIONS)
*     !LYNX CALCBO OVER CALCLM
*     !CALCLM
*
*  A recursive-descent parser: EXPR, TERM and FACTOR call each other
*  with BAL,11 and keep their return addresses and left operands on a
*  stack of their own (register 1). The line is read with M:READ on
*  M:UC, the terminal's DCB in the JIT (X'8C2C'), and written with
*  M:WRITE there; COC adds no new line on M:UC, so we send NL (X'15').
*
         DEF      START
SP       EQU      1                 the stack pointer (an index)
IP       EQU      2                 the line's byte index
C        EQU      3                 the current character
V        EQU      8                 an expression's value
NL       EQU      X'15'             EBCDIC new line
*
START    CAL1,1   PROMPT            M:PC: '>' for our reads
         LI,6     0
         LI,4     41
CLEAR    STW,6    VARS-1,4          the variables to 0
         BDR,4    CLEAR
         LI,4     HI
         LI,5     10
         BAL,11   WRITELN
*
*  Each line: read it, fold it to upper case, then see what it is
*
NEXT     LI,SP    STACK             a fresh stack for each line
         LI,6     NL
         LI,5     80
         STB,6    LINE,5            a new line after the longest
         CAL1,1   READ              M:READ on M:UC
         LI,5     0
FOLD     LB,6     LINE,5
         CI,6     NL
         BE       FOLDED
         CI,6     X'81'             lower case a-z: X'81'-X'A9'
         BL       FOLD1
         CI,6     X'A9'
         BG       FOLD1
         AI,6     X'40'
         STB,6    LINE,5
FOLD1    AI,5     1
         B        FOLD
FOLDED   LI,IP    0
         BAL,11   SKIP              the first character
         CI,C     NL
         BE       NEXT              an empty line
         BAL,11   ISLET
         B        CALC              not a letter: an expression
         LW,6     IP                a letter: where it is
         LW,7     C                 and which
         BAL,11   ADV
         CI,C     X'7E'             '='
         BE       ASSIGN
         BAL,11   ISLET
         B        BACK              a letter alone: a variable
         CI,7     X'D7'             'P...': PRINT
         BE       PRINT
         CI,7     X'C2'             'B...': BYE
         BE       BYE
         B        SYNTAX
BACK     LW,IP    6                 back to the variable
         LB,C     LINE,IP
         B        CALC
PRINT    BAL,11   ISLET             past the rest of the word
         B        PRINT2
         AI,IP    1
         LB,C     LINE,IP
         B        PRINT
PRINT2   BAL,11   SKIP
CALC     BAL,11   EXPR
         CI,C     NL                all of the line used?
         BNE      SYNTAX
         BAL,11   PRNUM
         B        NEXT
ASSIGN   AI,7     -X'C1'            the variable's index
         STW,7    VARX
         BAL,11   ADV
         BAL,11   EXPR
         CI,C     NL
         BNE      SYNTAX
         LW,7     VARX
         STW,V    VARS,7
         B        NEXT
BYE      CAL1,9   1                 M:EXIT
SYNTAX   LI,4     SYNMSG
         LI,5     12
         BAL,11   WRITELN
         B        NEXT
DIVZERO  LI,4     DIVMSG
         LI,5     16
         BAL,11   WRITELN
         B        NEXT
*
*  EXPR: TERM, then any number of + TERM or - TERM. The value in V,
*  the next character in C.
*
EXPR     AI,SP    1
         STW,11   0,SP              push the return
         BAL,11   TERM
EXPR1    CI,C     X'4E'             '+'
         BE       EXPRADD
         CI,C     X'60'             '-'
         BE       EXPRSUB
         LW,11    0,SP              pop it
         AI,SP    -1
         B        *11
EXPRADD  AI,SP    1
         STW,V    0,SP              the left operand
         BAL,11   ADV
         BAL,11   TERM
         AW,V     0,SP
         AI,SP    -1
         B        EXPR1
EXPRSUB  AI,SP    1
         STW,V    0,SP
         BAL,11   ADV
         BAL,11   TERM
         LCW,V    V                 minus the right operand
         AW,V     0,SP
         AI,SP    -1
         B        EXPR1
*
*  TERM: FACTOR, then any number of * FACTOR or / FACTOR
*
TERM     AI,SP    1
         STW,11   0,SP
         BAL,11   FACTOR
TERM1    CI,C     X'5C'             '*'
         BE       TERMMUL
         CI,C     X'61'             '/'
         BE       TERMDIV
         LW,11    0,SP
         AI,SP    -1
         B        *11
TERMMUL  AI,SP    1
         STW,V    0,SP
         BAL,11   ADV
         BAL,11   FACTOR
         LW,9     0,SP              the left operand
         MW,9     V                 times the right: low word in 9
         LW,V     9
         AI,SP    -1
         B        TERM1
TERMDIV  AI,SP    1
         STW,V    0,SP
         BAL,11   ADV
         BAL,11   FACTOR
         CI,V     0
         BE       DIVZERO
         LW,7     0,SP              the dividend in 6 and 7
         LW,6     7
         SAS,6    -31               its sign through 6
         DW,6     V                 the quotient in 7
         LW,V     7
         AI,SP    -1
         B        TERM1
*
*  FACTOR: a number, a variable, ( EXPR ), or - FACTOR
*
FACTOR   AI,SP    1
         STW,11   0,SP
         CI,C     X'4D'             '('
         BE       PAREN
         CI,C     X'60'             '-'
         BE       NEGATE
         BAL,11   ISDIG
         B        FACTVAR
         LI,V     0                 a number: its digits
NUMBER   LW,9     V
         MW,9     TEN
         LW,V     9
         AI,C     -X'F0'
         AW,V     C
         AI,IP    1
         LB,C     LINE,IP
         BAL,11   ISDIG
         B        FACTSKIP
         B        NUMBER
FACTSKIP BAL,11   SKIP
FACTRET  LW,11    0,SP
         AI,SP    -1
         B        *11
FACTVAR  BAL,11   ISLET
         B        SYNTAX
         AI,C     -X'C1'
         LW,V     VARS,C
         BAL,11   ADV
         B        FACTRET
PAREN    BAL,11   ADV
         BAL,11   EXPR
         CI,C     X'5D'             ')'
         BNE      SYNTAX
         BAL,11   ADV
         B        FACTRET
NEGATE   BAL,11   ADV
         BAL,11   FACTOR
         LCW,V    V
         B        FACTRET
*
*  The scanner. ADV: past the character, then SKIP: past blanks. The
*  character in C. ISLET, ISDIG: return one word further if C is one.
*
ADV      AI,IP    1
SKIP     LB,C     LINE,IP
         CI,C     X'40'             a blank
         BNE      *11
         AI,IP    1
         B        SKIP
ISLET    CI,C     X'C1'             A
         BL       *11
         CI,C     X'E9'             Z
         BG       *11
         AI,11    1                 (11 can't index: no B 1,11)
         B        *11
ISDIG    CI,C     X'F0'
         BL       *11
         CI,C     X'F9'
         BG       *11
         AI,11    1                 (11 can't index: no B 1,11)
         B        *11
*
*  PRNUM: V in decimal, then NL. The digits from the right in DIG.
*
PRNUM    LW,7     V
         LI,5     12
         CI,7     0
         BGE      PRNUM1
         LCW,7    7                 the magnitude
PRNUM1   LI,6     0
         DW,6     TEN               the quotient in 7, the digit in 6
         AI,6     X'F0'
         AI,5     -1
         STB,6    DIG,5
         CI,7     0
         BNE      PRNUM1
         CI,V     0
         BGE      PRNUM2
         LI,6     X'60'             '-'
         AI,5     -1
         STB,6    DIG,5
PRNUM2   LI,4     0
PRNUM3   LB,6     DIG,5             to OUT, from its first byte
         STB,6    OUT,4
         AI,4     1
         AI,5     1
         CI,5     12
         BL       PRNUM3
         LI,6     NL
         STB,6    OUT,4
         AI,4     1
         LW,5     4                 the byte count
         LI,4     OUT
*
*  WRITE: M:WRITE on M:UC of R5 bytes at the word R4. WRITELN: then NL.
*
WRITE    STW,4    WRFPT+2
         STW,5    WRFPT+3
         CAL1,1   WRFPT
         B        *11
WRITELN  STW,11   SAVE11
         BAL,11   WRITE
         LI,4     NLW
         LI,5     1
         BAL,11   WRITE
         LW,11    SAVE11
         B        *11
*
*  FPTs: the code and DCB (M:UC), the presence bits, the parameters
*
PROMPT   DATA     X'2C00006E'       M:PC '>'
READ     DATA     X'10008C2C',X'30000000',LINE,80
WRFPT    DATA     X'11008C2C',X'30000000',0,0
TEN      DATA     10
NLW      DATA     X'15000000'
VARX     DATA     0
SAVE11   DATA     0
HI       TEXT     'CALC READY'
SYNMSG   TEXT     'SYNTAX ERROR'
DIVMSG   TEXT     'DIVISION BY ZERO'
LINE     RES      21
DIG      RES      3
OUT      RES      4
VARS     RES      41                indexed by letter - X'C1'
STACK    RES      100
         END      START
