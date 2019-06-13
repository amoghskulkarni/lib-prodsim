import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="prodsim",
    version="0.0.1",
    author="Amogh Kulkarni",
    author_email="amoghkulkarni.kop@gmail.com",
    description="A small library for building production line simulations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/amoghskulkarni/lib-prodsim",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
