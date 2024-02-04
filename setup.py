from setuptools import setup

setup(
    name='ftpsync',
    version='0.0',
    license='MIT',
    url = 'https://github.com/GillesArcas/ftpsync',
    author = 'Gilles Arcas',
    author_email = 'gilles.arcas@gmail.com',
    entry_points = {
        'console_scripts': ['ftpsync=ftpsync:main'],
    },
    zip_safe=False,
    install_requires = [
    ]
)
