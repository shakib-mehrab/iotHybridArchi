# HybridGuard Framework — Step-by-Step Setup & Test Guide

A step-by-step guide to running and testing this framework.

## 1. Start Docker
**Terminal 1 (Windows Terminal):**
```bash
docker desktop start
```

## 2. Check if Any Container Is Running
**Terminal 2 (WSL / Windows):**
```bash
docker ps
```
(If Fabric is running, the container will show up; otherwise, it won't.)

## 3. Run the Fabric Network
**Terminal 2 (WSL):**
```bash
cd ~/projects/iotHybridArchi/fabric/fabric-samples/test-network
./network.sh up -s couchdb
```

## 4. Check the Channel List
**Terminal (WSL):**
```bash
peer channel list
```
(This will return "command not found" — you first need to load the Fabric environment.)

## 5. Load the Fabric Environment
**Terminal 2 (WSL):**
```bash
cd ~/projects/iotHybridArchi/fabric/fabric-samples/test-network
export PATH=$PATH:/home/mehrab/projects/iotHybridArchi/fabric/fabric-samples/bin
export FABRIC_CFG_PATH=/home/mehrab/projects/iotHybridArchi/fabric/fabric-samples/config
source scripts/envVar.sh
setGlobals 1   # selects Organization 1; use setGlobals 2 for Organization 2
peer channel list
```
If any channel is missing, create it (see next step).

## 6. Create a Channel
**Terminal 2 (WSL):**
```bash
cd ~/projects/iotHybridArchi/fabric/fabric-samples/test-network
./network.sh createChannel -c hybridguard-channel
```
This creates the channel in both organizations.
```bash
peer channel list
```
You should now see your channel name listed.

## 7. Check if the Chaincode Is Deployed
**Terminal 2 (WSL):**
```bash
cd ~/projects/iotHybridArchi/fabric/fabric-samples/test-network
peer lifecycle chaincode queryinstalled
peer lifecycle chaincode querycommitted -C hybridguard-channel
```
If nothing is returned, no chaincode is deployed yet.

## 8. Deploy the Chaincode
**Terminal 2 (WSL):**
```bash
cd ~/projects/iotHybridArchi/fabric/fabric-samples/test-network
./network.sh deployCC \
  -ccn hybridguard \
  -ccp /home/mehrab/projects/iotHybridArchi/chaincode/hybridguard \
  -ccl go \
  -c hybridguard-channel
```
Then verify again with:
```bash
peer lifecycle chaincode querycommitted -C hybridguard-channel
```
You should see output similar to:
`Name: hybridguard, Version: 1.0, Sequence: 1, Endorsement Plugin: escc, Validation Plugin: vscc`

## 9. Optional: Test the Chaincode
**Terminal 2 (WSL), from the `test-network` path:**

**Register a device:**
```bash
export ORDERER_CA=/home/mehrab/projects/iotHybridArchi/fabric/fabric-samples/test-network/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem

export CORE_PEER_TLS_ROOTCERT_FILE=/home/mehrab/projects/iotHybridArchi/fabric/fabric-samples/test-network/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt

export ORG2_TLS=/home/mehrab/projects/iotHybridArchi/fabric/fabric-samples/test-network/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt
```

**Invoke:**
```bash
peer chaincode invoke \
  -o localhost:7050 \
  --ordererTLSHostnameOverride orderer.example.com \
  --tls \
  --cafile "$ORDERER_CA" \
  -C hybridguard-channel \
  -n hybridguard \
  --peerAddresses localhost:7051 \
  --tlsRootCertFiles "$CORE_PEER_TLS_ROOTCERT_FILE" \
  --peerAddresses localhost:9051 \
  --tlsRootCertFiles "$ORG2_TLS" \
  -c '{"function":"RegisterDevice","Args":["manual-device-01","123456789abcdef","HybridGuardOrg"]}'
```

**Query:**
```bash
peer chaincode query \
  -C hybridguard-channel \
  -n hybridguard \
  -c '{"function":"GetDevice","Args":["sim-device-01"]}'
```
If JSON is returned, proceed to the next step.

---

Now that Fabric is up and running, we'll verify the other layer — the Windows side. All the following terminals run on Windows.

## 10. Activate IPFS
**Terminal 3:**
```powershell
cd "F:\4 1 Research\hybrid-architecture\iotHybridArchi"
.\hybridguard-env\Scripts\activate
ipfs daemon
```

## 11. Start the Gateway
**Terminal 4:**
```powershell
cd "F:\4 1 Research\hybrid-architecture\iotHybridArchi"
.\hybridguard-env\Scripts\activate
python .\gateway\gateway_server.py
```
Verify at: http://127.0.0.1:8080/health

## 12. Start the FL Server
**Terminal 5:**
```powershell
cd "F:\4 1 Research\hybrid-architecture\iotHybridArchi"
.\hybridguard-env\Scripts\activate
python .\fl\fl_server.py
```
Verify at: http://127.0.0.1:8081/status

## 13. Start the FL Receiver
**Terminal 6:**
```powershell
cd "F:\4 1 Research\hybrid-architecture\iotHybridArchi"
.\hybridguard-env\Scripts\activate
python edge\fl_receiver.py --port 8082 --device sim-device-01   # any device name works
```
Verify at: http://127.0.0.1:8082/health

## 14. Start the Simulator
**Terminal 7:**
```powershell
cd "F:\4 1 Research\hybrid-architecture\iotHybridArchi"
.\hybridguard-env\Scripts\activate
python edge\simulator.py --device sim-device-01 --scenario NORMAL_OPERATION --duration 30
```
For gateway logs:
```powershell
Get-Content logs\gateway.log -Tail 30
```
For FL status:
```powershell
Invoke-RestMethod http://127.0.0.1:8081/status | ConvertTo-Json
```

## 15. Start the Dashboard
**Terminal 8:**
```powershell
cd "F:\4 1 Research\hybrid-architecture\iotHybridArchi"
.\hybridguard-env\Scripts\activate
python Dashboard\app.py
```
Open: http://127.0.0.1:8090