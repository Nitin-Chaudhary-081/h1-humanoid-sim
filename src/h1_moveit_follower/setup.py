from setuptools import find_packages, setup

package_name = "h1_moveit_follower"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/follower.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="robot-agent",
    maintainer_email="robot-agent@example.com",
    description="MoveIt2 FollowJointTrajectory action server bridging to H1 cmd_pos topics",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "follower_node = h1_moveit_follower.follower_node:main",
        ],
    },
)