from setuptools import find_packages, setup


setup(
    name="claim-layer",
    version="2.0.0",
    description="Compute truth from evidence, not text",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
    license="LicenseRef-ClaimLayer-BSL-1.1",
)
