@echo off
SET users=pool-southx-usd.conf
if not exist pool-southx-usd.conf (
  if exist pool-southx-usd.conf.txt (
    SET users=pool-southx-usd.conf.txt
  ) else (
    @echo on
    echo error: You must specify a file called pool-southx-usd.conf with your exchange data
    pause
    exit
  )
)
@echo on
..\..\python\client.py %users%
