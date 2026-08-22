from setuptools import find_packages, setup

package_name = "h1_rl_policy"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/rl_policy.yaml"]),
        ("share/" + package_name + "/assets", ["assets/h1_stand.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="robot-agent",
    maintainer_email="robot-agent@example.com",
    description="M8 RL: numpy stand policy (MuJoCo proxy) + ONNX export",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "rl_train = h1_rl_policy.train:main",
            "rl_export = h1_rl_policy.export_onnx:main",
        ],
    },
)
