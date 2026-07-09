"""MediProof synthetic data generator (MediClaim-Bench).

Public repo contains synthetic data only (plan §11). Everything here is seeded for
byte-identical reproducibility.
"""

from datagen.sampler import sample_claim

__all__ = ["sample_claim"]
