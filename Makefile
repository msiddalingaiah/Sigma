
# nmake file

SRC = src
DEST = .
# JAVAHOME = c:\j2sdk1.4.1_01
JAVAHOME = c:\j2sdk1.4.0
# JAVAHOME = c:\j2sdk1.4.0_02
RUNTIME = $(JAVAHOME)\jre\lib\rt.jar
CLASSPATH = $(DEST)
JAVA = $(JAVAHOME)\bin\java
JAVAC = $(JAVAHOME)\bin\javac
# JAVAC = c:\Madhu\bin\bcj
JAR = $(JAVAHOME)\bin\jar

all: classes

classes:
	$(JAVAC) -d $(DEST) -classpath $(CLASSPATH) \
		$(SRC)\*.java $(SRC)\cpu\*.java $(SRC)\iop\*.java \
		$(SRC)\sigma6\*.java $(SRC)\gui\*.java

run:
	$(JAVA) -classpath $(CLASSPATH) \
		com.madhu.sigma.sigma6.Sigma6Computer sigma6.props

rundis:
	$(JAVA) -classpath $(CLASSPATH) com.madhu.sigma.Disassembler 9autoall.dp

rungui:
	$(JAVA) -classpath $(CLASSPATH) \
		com.madhu.sigma.gui.PCPFrame sigma6.props

jar:
	$(JAR) -cmf manifest.txt sigma6.jar com

clean:
	-del $(DEST)\com\madhu\sigma\*.class
	-del $(DEST)\com\madhu\sigma\cpu\*.class
	-del $(DEST)\com\madhu\sigma\iop\*.class
	-del $(DEST)\com\madhu\sigma\sigma6\*.class
	-del $(DEST)\com\madhu\sigma\gui\*.class
	-del sigma6.jar
