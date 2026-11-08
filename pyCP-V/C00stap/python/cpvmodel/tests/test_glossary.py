"""The glossary and the generated docs can't drift: every public name is mapped, every
citation holds, and the files in docs/model/ are what the model generates."""

from cpvmodel import glossary
from cpvmodel.generated import staleDocs


def testEveryPublicNameHasACpvRef():
    assert glossary.missingRefs() == []


def testEverySymbolIsInTheCitedSourceLines():
    assert glossary.sourceProblems() == []


def testGeneratedDocsAreCurrent():
    assert staleDocs() == [], "run: python -m cpvmodel docs"


def testSourceRangesParse():
    ref = glossary.cpv("S:CUIS", source="SSDAT.txt:51, SCHED.txt:1065-1084")
    assert ref.ranges() == [("SSDAT.txt", 51, 51), ("SCHED.txt", 1065, 1084)]
