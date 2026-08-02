# Rome Triumvirate Scenario — Territory & Faction Reference

## Faction IDs

octavian(屋大维/Octavian), antony(马克·安东尼/Mark Antony), cleopatra(克利奥帕特拉/Cleopatra), senate(罗马元老院/Senate), sextus_pompey(塞克斯图斯·庞培/Sextus Pompey)

## Territory IDs

octavian core: roma(罗马/Rome), cisalpine_gaul(山南高卢), transalpine_gaul(山北高卢), hispania_citerior(近西班牙), narbonensis(纳尔旁高卢)
antony core: macedonia(马其顿), syria(叙利亚), asia(亚细亚), graecia(希腊)
cleopatra core: aegyptus(埃及), cyrenaica(昔兰尼加), cyprus(塞浦路斯)
pompey core: sicilia(西西里), sardinia(撒丁尼亚)
senate: roma(罗马) — shared with octavian
disputed: africa(阿非利加)

## Rome Scenario Parse Examples

### Example 1: Form Triumvirate Alliance
Player command (as Octavian):
```
Propose a renewed triumvirate with Mark Antony. We must present a united front
against Sextus Pompey who threatens our grain supply from Sicily.
Send 5 legions to Cisalpine Gaul to secure the northern frontier.
```

Expected output:
```json
{
  "commands": [
    {
      "type": "negotiate",
      "params": {
        "target_faction": "antony",
        "proposal": "Renew triumvirate alliance against Sextus Pompey",
        "action": "form_alliance"
      },
      "notes": "Political strategy: renewing triumvirate with Antony to present united front. Common enemy: Sextus Pompey threatening grain supply."
    },
    {
      "type": "move",
      "params": {
        "destination": "cisalpine_gaul",
        "amount": 25000,
        "unit_type": "infantry"
      },
      "notes": "Northern defense: 5 legions (~25,000 men) to secure Cisalpine Gaul frontier against potential Gallic incursions."
    }
  ]
}
```

### Example 2: Naval Campaign
Player command (as Octavian):
```
Launch naval offensive against Sextus Pompey's fleet in Sicily.
Agrippa commands the fleet from Narbonensis with 200 warships.
Also improve grain storage in Rome to prepare for siege.
```

Expected output:
```json
{
  "commands": [
    {
      "type": "attack",
      "params": {
        "target_territory": "sicilia",
        "source_territory": "narbonensis",
        "amount": 200,
        "unit_type": "navy"
      },
      "notes": "Naval campaign: Agrippa leads 200 warships from Narbonensis against Pompey's Sicilian fleet. Control of Sicily = control of grain supply."
    },
    {
      "type": "develop",
      "params": {
        "territory": "roma"
      },
      "notes": "Infrastructure: improve grain storage in Rome to withstand potential grain supply disruption during Sicilian campaign."
    }
  ]
}
```

### Example 3: Break Alliance
Player command (as Octavian):
```
Antony has betrayed Rome by marrying Cleopatra and giving Roman provinces to Egypt.
Break our alliance with Antony immediately. Recall our legions from Greece.
Fortify Brundisium against possible invasion.
```

Expected output:
```json
{
  "commands": [
    {
      "type": "negotiate",
      "params": {
        "target_faction": "antony",
        "proposal": "Break alliance due to betrayal — Antony married Cleopatra and ceded Roman provinces to Egypt",
        "action": "break_alliance"
      },
      "notes": "Political crisis: Antony's marriage to Cleopatra and cession of Roman territory constitutes betrayal. Alliance must be formally dissolved."
    },
    {
      "type": "move",
      "params": {
        "destination": "roma",
        "source_territory": "graecia"
      },
      "notes": "Strategic withdrawal: recalling legions from Greece back to Italy in preparation for potential civil war."
    },
    {
      "type": "defend",
      "params": {
        "territory": "roma"
      },
      "notes": "Homeland defense: fortifying Italian coast against possible Antonian/Egyptian naval invasion."
    }
  ]
}
```

### Example 4: Diplomatic Maneuvering
Player command (as Antony):
```
Send envoys to the Senate to propose reconciliation. Offer to resign
my eastern command in exchange for retaining Egypt as a client kingdom.
Meanwhile, develop Syria's agricultural base and train auxiliaries.
```

Expected output:
```json
{
  "commands": [
    {
      "type": "negotiate",
      "params": {
        "target_faction": "senate",
        "proposal": "Reconciliation: resign eastern command, retain Egypt as client kingdom",
        "action": "form_alliance"
      },
      "notes": "Diplomatic gambit: proposing compromise with Senate — give up eastern provinces to keep Egypt. Tests Senate's willingness to avoid civil war."
    },
    {
      "type": "develop",
      "params": {
        "territory": "syria"
      },
      "notes": "Economic preparation: developing Syrian agriculture to ensure food independence if grain supply from Egypt is cut."
    },
    {
      "type": "train",
      "params": {
        "territory": "asia"
      },
      "notes": "Military: training auxiliary troops in Asia Minor to supplement legions."
    }
  ]
}
```

### Key Differences from Three Kingdoms / Nanming

- **Naval warfare is central**: Sicily, grain supply, and control of Mediterranean shipping lanes are critical
- **Territory IDs are English/Latin**: cisalpine_gaul, transalpine_gaul, hispania_citerior, etc.
- **Faction IDs are English**: octavian, antony, cleopatra, senate, sextus_pompey
- **Politics is multi-polar**: Triumvirate dynamics mean 3-way alliances and betrayals are common
- **No "出川" equivalent**: Roman legions "march from X to Y" not "leave Sichuan" — territory movement is straightforward
- **Break alliances are common**: The historical period is defined by alliance formation and dissolution
