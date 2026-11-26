from setuptools import find_packages, setup

package_name = "hi04_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml", "README.md"]),
        (f"share/{package_name}/config", ["config/hi04.yaml"]),
        (f"share/{package_name}/launch", ["launch/hi04.launch.py"]),
    ],
    install_requires=["setuptools", "python-can>=4.0"],
    zip_safe=True,
    maintainer="Your Name",
    maintainer_email="you@example.com",
    description="ROS2 SocketCAN driver for the HI04 CANopen TPDO sensor.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "hi04_node = hi04_ros.hi04_node:main",
        ],
    },
)
