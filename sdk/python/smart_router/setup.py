from setuptools import find_packages, setup


setup(
    name="smart-router",
    version="0.1.0",
    description="Algorithm framework for payment orchestration route decisions.",
    packages=find_packages(),
    python_requires=">=3.10",
    include_package_data=True,
)
