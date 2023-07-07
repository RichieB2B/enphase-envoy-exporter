#! /usr/bin/python3
import sys
import time
import json
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import ReadTimeout, ConnectTimeout
from urllib3 import disable_warnings
from urllib3.exceptions import NewConnectionError, MaxRetryError, InsecureRequestWarning
import prometheus_client as prom
import config

disable_warnings(InsecureRequestWarning)

auth = HTTPDigestAuth(config.user, config.password)

def readEnvoy(url):
  try:
    result = requests.get(url, auth=auth, verify=False, timeout=5)
  except (ReadTimeout, ConnectTimeout, NewConnectionError, MaxRetryError) as e:
    return {}
  try:
    data = result.json()
  except Exception as e:
    if not 'The page you tried to view does not exist' in result.text:
      print(f'{type(e).__name__}: {str(e)}')
    return {}
  return data

if __name__ == '__main__':
  envoy_power         = prom.Gauge('envoy_power'              , 'Power in Watt', unit='watts')
  envoy_production    = prom.Counter('envoy_production'       , 'Production in Wh', unit='whs')
  envoy_active        = prom.Gauge('envoy_active'             , 'Number of active inverters', unit='count')
  envoy_readingtime   = prom.Gauge('envoy_readingtime'        , 'Time of reading')
  inverter_power      = prom.Gauge('envoy_inverter_power'     , 'Power in Watt', ['serialnumber', 'array', 'type'], unit='watts')
  inverter_lastreport = prom.Gauge('envoy_inverter_lastreport', 'Time in epoch', ['serialnumber', 'array'])
  updated             = prom.Gauge('envoy_updated'            , 'Envoy client last updated')
  up                  = prom.Gauge('envoy_up'                 , 'Envoy client status')
  prom.start_http_server(8085)

  while True:
    dataReceived = False
    # Force comm check otherwise data is only updated every 15 minutes
    readEnvoy(f'https://{config.host}/installer/pcu_comm_check')
    # Get general production data
    data = readEnvoy(f'https://{config.host}/production.json')
    prod = data.get('production',[])
    p = {}
    for i in prod:
      if i.get('type') == 'inverters':
        p = i
    if p:
      dataReceived = True
      up.set(1)
      updated.set(time.time())
      if p.keys() >= {'readingTime','wNow','whLifetime','activeCount'}:
        envoy_power.set(p['wNow'])
        envoy_production._value.set(p['whLifetime'])
        envoy_active.set(p['activeCount'])
        envoy_readingtime.set(p['readingTime'])
    # Get inverter production data
    data = readEnvoy(f'https://{config.host}/api/v1/production/inverters')
    if data:
      dataReceived = True
      up.set(1)
      updated.set(time.time())
      for i in data:
        if i.keys() >= {'serialNumber','lastReportDate','lastReportWatts','maxReportWatts'}:
          array = config.arrays.get(i['serialNumber'], 'unknown')
          inverter_power.labels(i['serialNumber'], array, 'last').set(i['lastReportWatts'])
          inverter_power.labels(i['serialNumber'], array, 'max').set(i['maxReportWatts'])
          inverter_lastreport.labels(i['serialNumber'], array).set(i['lastReportDate'])
    if not dataReceived:
      up.set(0)

    time.sleep(30)
