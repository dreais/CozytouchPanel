"""Read-only Cozytouch diagnostic: no actions, changes, or refresh commands."""
import asyncio
from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from dashboard import VENDORS, HEATER_TYPE, load_mapping, private_id
from config import get_credentials

KEYS = (
    'core:ComfortRoomTemperatureState',
    'core:EcoRoomTemperatureState',
    'io:SetpointLoweringTemperatureInProgModeState',
    'io:EffectiveTemperatureSetpointState',
    'core:DerogatedTargetTemperatureState',
    'core:TargetTemperatureState',
    'core:PreviousTargetTemperatureState',
    'io:TimerForTransitoryStateState',
    'io:TargetHeatingLevelState',
    'core:OperatingModeState',
    'io:InternalExternalSchedulingTypeState',
    'core:StatusState',
)
COMMANDS = ('setEcoTemperature', 'setSetpointLoweringTemperatureInProgMode',
            'setComfortTemperature', 'setTimeProgram', 'refreshTimeProgram')

async def main():
    print('READ-ONLY Cozytouch diagnosis — no heater commands will be sent.\n')
    choice, user, pwd = get_credentials()
    print(f'Using {VENDORS[choice][0]} backend from local .env')
    mapping = load_mapping() or {}
    if not mapping:
        raise SystemExit('rooms.json not found; copy it from the working dashboard directory.')
    async with OverkizClient(server=VENDORS[choice][1], credentials=UsernamePasswordCredentials(user, pwd)) as client:
        await client.login(register_event_listener=False)
        devices = await client.get_devices()
        heaters = [d for d in devices if getattr(d, 'controllable_name', None) == HEATER_TYPE]
        print('\nFound', len(heaters), 'heater(s). No device URLs will be printed.')
        for dev in heaters:
            room = mapping.get(private_id(dev), 'UNMAPPED')
            print('\n---', room, '---')
            # GET endpoint only; no device refresh or command execution.
            states = {str(s.name): s.value for s in await client.get_state(dev.device_url)}
            for key in KEYS:
                print(key, '=', states.get(key, '<not reported>'))
            print('Commands advertised:')
            for command in COMMANDS:
                print(' ', command, ':', bool(dev.supports_command(command)))
                if dev.supports_command(command):
                    definition = dev.get_command_definition(command)
                    print('   expected parameter count:', getattr(definition, 'nparams', 'unknown'))
            program_states = [k for k in states if 'program' in k.lower() or 'schedul' in k.lower()]
            print('Schedule/program state names:', program_states or '(none available in GET states)')
            comfort = states.get('core:ComfortRoomTemperatureState')
            offset = states.get('io:SetpointLoweringTemperatureInProgModeState')
            effective = states.get('io:EffectiveTemperatureSetpointState')
            override = states.get('core:DerogatedTargetTemperatureState')
            if isinstance(comfort, (int, float)) and isinstance(offset, (int, float)):
                nominal = comfort - offset
                print('Nominal ECO target (comfort minus offset):', round(nominal, 2))
                if isinstance(effective, (int, float)) and abs(effective - nominal) > 0.11:
                    print('NOTE: Effective target differs from nominal ECO target. Investigate active override.')
            if isinstance(override, (int, float)) and override > 0:
                print('NOTE: Nonzero derogated target is reported; its exact expiry is unknown.')

        print('\nRecent execution outcome metadata (cloud history):')
        try:
            history = await client.get_execution_history()
            print('History entries available:', len(history))
            for entry in history[:8]:
                # Exclude execution IDs, raw descriptions, devices, parameters, and URLs.
                bits = []
                for attr in ('status', 'state', 'execution_state', 'execution_status', 'type'):
                    value = getattr(entry, attr, None)
                    if value is not None and isinstance(value, (str, int, float)):
                        bits.append(f'{attr}={value[:40] if isinstance(value, str) else value}')
                print(' ', ', '.join(bits) or f'Entry type={type(entry).__name__}, no simple status field')
        except Exception as exc:
            print('History unavailable:', type(exc).__name__)
        print('\nDone. Read-only; nothing modified.')

if __name__ == '__main__':
    asyncio.run(main())
