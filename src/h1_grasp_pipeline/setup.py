from setuptools import find_packages, setup

package_name = "h1_grasp_pipeline"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/grasp.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="robot-agent",
    maintainer_email="robot-agent@example.com",
    description="M5: Grasp pipeline — perception (ArUco) -> grasp pose generation -> trajectory -> MoveIt2 follower",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "grasp_node = h1_grasp_pipeline.grasp_node:main",
        ],
    },
)