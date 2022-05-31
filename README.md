# Sigma

Sigma is an [SDS/XDS Sigma computer](https://en.wikipedia.org/wiki/SDS_Sigma_series) simulator written in Java.
It was originally developed by Madhu Siddalingaiah with significant
help from Keith Calkins.

The simulator is capable of running many of the diagnostics successfully,
but cannot yet fully boot CP-V. The processor is largely functional, but
many of IOP processors and interaction with the CPU is incomplete.

The simulator configuration is found in sigma6.props, please
see that file for configuration details.

To run the simulator, issue any of the following commands:

```
ant run
./sigma
java -jar sigma.jar sigma6.props
```

A graphical Processor Control Panel (PCP) should appear.
To start a simulation:

1. Enter a valid unit number (lower left)
2. Press Reset to reset the CPU and IOPs
3. Press Load to load boot instructions
4. Press Run to start execution

Stop stops execution, Step performs single instruction execution.

Data entry follow Sigma conventions, hexadecimal values are prefixed
with a single ".".

When the processor is stopped, processor state can be viewed or
modified.
