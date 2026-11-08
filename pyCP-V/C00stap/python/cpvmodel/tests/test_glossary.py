"""The glossary and the generated docs can't drift: every public name is mapped, every
citation holds, and the files in docs/model/ are what the model generates."""

import pytest

from cpvmodel import glossary
from cpvmodel.glossary import SOURCE_ROOT
from cpvmodel.generated import staleDocs

# The CP-V listings (c00co/) are kept out of the repository, so these tests need a local copy.
needsSource = pytest.mark.skipif(not (SOURCE_ROOT / "SCHED.txt").exists(),
                                 reason="the CP-V source listings (c00co/) aren't here")


def testEveryPublicNameHasACpvRef():
    assert glossary.missingRefs() == []


@needsSource
def testEverySymbolIsInTheCitedSourceLines():
    assert glossary.sourceProblems() == []


def testGeneratedDocsAreCurrent():
    assert staleDocs() == [], "run: python -m cpvmodel docs"


def testSourceRangesParse():
    ref = glossary.cpv("S:CUIS", source="SSDAT.txt:51, SCHED.txt:1065-1084")
    assert ref.ranges() == [("SSDAT.txt", 51, 51), ("SCHED.txt", 1065, 1084)]
