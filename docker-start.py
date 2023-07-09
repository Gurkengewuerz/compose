#!/usr/bin/python3

import glob
import os
import pathlib

DOCKER_COMPOSE_BIN = "/usr/bin/docker-compose"

PRIORITIES = [
    "HIHGEST",
    "HIGH",
    "NORMAL",
    "LOW",
    "LOWEST",
]

MODULES = []

class Module:

    def __init__(self, name, directory):
        self.name = name
        self.directory = directory
        self.priority = None
        self.disabled = None
    
    def get_docker_compose(self):
        return pathlib.PurePath(self.directory, "docker-compose.yml")

    def get_priority(self):
        if self.priority:
            return self.priority
        
        prioPath = pathlib.PurePath(self.directory, ".priority")
        try:
            with open(prioPath, "r") as f:
                self.priority = f.read().strip().upper()
        except Exception:
            self.priority = "NORMAL"
        return self.priority
    
    def is_disabled(self):
        if self.disabled:
            return self.disabled
        
        prioPath = pathlib.PurePath(self.directory, ".disabled")
        self.disabled = os.path.isfile(prioPath)
        return self.disabled

    def __str__(self):
        return "name={};relative_directory={};priority={};disabled={}".format(self.name, self.directory, self.get_priority(), self.is_disabled())

filePath = os.path.abspath(__file__)
scriptDir = pathlib.Path(filePath).parent

for dockerFileName in ["docker-compose.yml", "docker-compose.yaml"]:
    asPath = pathlib.PurePath(scriptDir, "**", dockerFileName)
    for dockerFile in glob.glob(str(asPath)):
        asPath = pathlib.Path(dockerFile)
        parentAsPath = pathlib.Path(asPath.parent)
        module = Module(parentAsPath.name.lower(), asPath.parent)
        MODULES.append(module)

tmpModules = []
for prio in PRIORITIES:
    for module in MODULES:
        if module.get_priority() == prio:
            tmpModules.append(module)

MODULES = tmpModules

for module in MODULES:
    print()
    print(module)
    if module.is_disabled():
        print("Skipping module because it is disabled...")
        continue
    os.chdir(str(module.directory))
    os.system("{0} up --build -d".format(DOCKER_COMPOSE_BIN))
    os.chdir(str(scriptDir))

print()
print()
print("Done!")