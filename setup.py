"""Setup configuration for Terraform Drift Detector."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [
        line.strip()
        for line in fh
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="terraform-drift-detector",
    version="1.0.0",
    author="Project Maintainers",
    author_email="noreply@example.invalid",
    description="Automated Terraform state drift detection with scheduled checks, alerting, and actionable reports",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/shivajichaprana/terraform-drift-detector",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "drift-detector=detector.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
        "Topic :: Software Development :: Build Tools",
    ],
    keywords="terraform drift detection infrastructure devops",
)
