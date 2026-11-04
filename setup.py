from setuptools import setup

setup(
    name='jellysports',
    version='2.0.0',
    author='Joel Kreisel',
    packages=['jellysports', 'jellysports.util'],
    include_package_data=True,
    url='https://github.com/peaceful-octopus/jellysports',
    license='MIT',
    description='Collects live sports streams into m3u/XMLTV files for Jellyfin.',
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    python_requires='>=3.9',
    install_requires=[
        "requests>=2.31",
        "Pillow>=10.1",
        "selenium>=4.10",
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Telecommunications Industry',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
)
