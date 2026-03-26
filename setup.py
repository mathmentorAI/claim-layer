from setuptools import find_packages, setup


setup(
    name="claim-layer",
    version="0.1.0",
    description="Reusable Evidence Intelligence core from Claim Layer",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
)
