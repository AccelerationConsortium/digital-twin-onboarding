"""Sim–Real: workflows run against the real instrument connectors in their simulation mode.

Nothing here opens a network connection or imports a SiLA SDK; the runner that starts
connectors lives in `ops/sim-real`. Results are simulation evidence from the connectors'
own simulators, never physical execution.
"""
