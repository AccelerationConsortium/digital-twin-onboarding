"""The three parts of a materials experiment: prepare, characterize, test.

Preparing makes the sample. A measurement characterizes it when it asks what the sample
is, and tests it when it asks how well the sample does the job the experiment is after.
The same instrument can do either, so a twin that takes a reading is given both and the
paper step it is used for says which.
"""

STAGES = ("prepare", "characterize", "test")

# Twins that take a reading only to make or portion a sample.
PREPARES = {"preparative-hplc", "flash-chromatography", "ac-purification", "ac-balance"}


def stages(key, operations):
    """The parts of an experiment a twin can take, from what it can do."""
    if "read" in operations and key not in PREPARES:
        return ["characterize", "test"]
    return ["prepare"]
