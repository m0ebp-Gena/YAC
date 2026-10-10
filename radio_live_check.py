"""Authorized hardware regression checks; capture and restore every tested VFO."""
import configparser,json,sys,re,traceback
from pathlib import Path
import serial
from serial.tools import list_ports
import yac
from modules.find_rad import RadioConnection,_open_serial,_usb_identity
def main():
    root=Path(__file__).resolve().parent
    records=[]
    def record(name,value,passed=True):
        item=dict(test=name,result=value,passed=passed); records.append(item); print(json.dumps(item),flush=True)
    def read(r,c,s):
        return yac._civ_response_data(yac._civ_exchange(r,c,s),r.civ_address,c,s)
    def restore(r,f,m,offset):
        if r.protocol=='CI-V':
            yac._set_icom_clarifier_enabled(r,1,False); yac._set_icom_clarifier_enabled(r,2,False)
        else: yac._set_yaesu_clarifier_state(r,False,False)
        yac._set_frequency(root,r,'en',f)
        if r.protocol=='CI-V':
            yac._civ_send(r,6,m)
            yac._set_icom_offset(r,offset[0]); yac._set_icom_clarifier_enabled(r,1,offset[1]); yac._set_icom_clarifier_enabled(r,2,offset[2])
        else:
            yac._set_mode(r,m); yac._set_yaesu_offset(r,offset[0]); yac._set_yaesu_clarifier_state(r,offset[1],offset[2])
        actual=(yac._icom_offset_hz(r),yac._icom_clarifier_enabled(r,1),yac._icom_clarifier_enabled(r,2)) if r.protocol=='CI-V' else yac._yaesu_offset_state(r)
        record('RESTORE '+r.model_name+' side '+str(yac._yaesu_vfo_side),dict(frequency=yac._current_frequency(root,r),mode=yac._current_mode_code(r),offset=actual), yac._current_frequency(root,r)==f and actual==offset and yac._current_mode_code(r)==(m[0] if isinstance(m,bytes) else m))
    def test(r):
        for side in ([0,1] if yac._ftx1(r) else [0]):
            yac._yaesu_vfo_side=side
            f=yac._current_frequency(root,r)
            m=read(r,4,None) if r.protocol=='CI-V' else yac._current_mode_code(r)
            offset=(yac._icom_offset_hz(r),yac._icom_clarifier_enabled(r,1),yac._icom_clarifier_enabled(r,2)) if r.protocol=='CI-V' else yac._yaesu_offset_state(r)
            if f is None or m is None or offset is None or None in offset:
                record('snapshot',str((f,m,offset)),False); continue
            tag=r.model_name+' side '+str(side)+' '
            record(tag+'snapshot',str((f,m,offset)))
            try:
                if r.protocol=='CI-V':
                    yac._set_icom_clarifier_enabled(r,1,False); yac._set_icom_clarifier_enabled(r,2,False)
                else: yac._set_yaesu_clarifier_state(r,False,False)
                for key in ['w','f','h','?']:
                    out=yac._dispatch(root,r,'en',key,None); record(tag+'key '+key,out, bool(out))
                for code,label in yac._available_modes(r):
                    ok=yac._set_mode(r,code); status=yac._radio_status(root,r,'en'); expected=yac._mode_name(r,code)
                    record(tag+'mode '+str(code),dict(ok=ok,status=status,expected=expected),ok and status.endswith(' '+expected))
                yac._set_mode(r, '2' if r.protocol=='CAT' else 1)
                for value in ['14.185123','7.159','145.5','0','nan','abc','471']:
                    out=yac._set_frequency(root,r,'en',value)
                    valid=value in ['14.185123','7.159','145.5']
                    record(tag+'frequency '+value,out, (out==yac._current_frequency(root,r)) if valid else out!=value)
                yac._set_frequency(root,r,'en','14.185123')
                for direction in [1,-1]:
                    before=yac._current_frequency(root,r); out=yac._step_frequency(root,r,'en',{'step_ssb':'2500'},direction)
                    record(tag+'step '+str(direction),out,abs(float(out)-float(before)-direction*.0025)<.000011 if re.fullmatch(r'\d+(\.\d+)?',out) else False)
                out=yac._round_frequency_to_khz(root,r,'en'); record(tag+'round',out,out=='14.185')
                for direction in [1,-1]:
                    before=yac._current_frequency(root,r); out=yac._band_change(root,r,'en',direction); after=yac._current_frequency(root,r)
                    record(tag+'band '+str(direction),dict(before=before,after=after,response=out),before!=after)
                record(tag+'zero offsets',yac._zero_offsets(r))
                for selection in [0,1,2]:
                    for direction in [1,-1]:
                        out=yac._offset_action(root,r,'en',selection,direction)
                        record(tag+'offset '+str((selection,direction)),out,not any(word in out.lower() for word in ['failed','could not','understood']))
                # Read tone settings before changing frequency/mode; restore in finally.
                if r.protocol=='CI-V':
                    tones={s:read(r,0x1B,s) for s in [0,1,2]}; tone_mode=read(r,0x16,0x5D)
                else:
                    tones={s:yac._cat_exchange(r,f'CN{side}{s};') for s in [0,1]}; tone_mode=yac._cat_exchange(r,f'CT{side};')
                record(tag+'tone snapshot',str((tones,tone_mode)))
                if all(tones.values()) and tone_mode:
                    try:
                        yac._set_frequency(root,r,'en','145.5'); yac._set_mode(r,'4' if r.protocol=='CAT' else 5)
                        for value,target in [('88.5','TX'),('88.5','Both'),('D023','Both'),('D023','TX'),('bad','Both')]:
                            out=yac._set_tone(root,r,'en',value,target)
                            expected = ('CTCSS 88.5 Hz '+target) if value=='88.5' else ('DCS 023 '+target)
                            allowed = value=='bad' or (r.protocol=='CAT' and value=='D023' and target=='TX')
                            record(tag+'tone '+value+' '+target,out,allowed or out==expected)
                    finally:
                        if r.protocol=='CI-V':
                            for s,data in tones.items(): yac._civ_send(r,0x1B,bytes([s])+data)
                            yac._civ_send(r,0x16,bytes([0x5D])+tone_mode)
                            ok=all(read(r,0x1B,s)==data for s,data in tones.items()) and read(r,0x16,0x5D)==tone_mode
                        else:
                            for response in tones.values(): yac._cat_exchange(r,response)
                            yac._cat_exchange(r,tone_mode)
                            ok=all(yac._cat_exchange(r,f'CN{side}{s};')==data for s,data in tones.items()) and yac._cat_exchange(r,f'CT{side};')==tone_mode
                        record(tag+'restore tones',ok,ok)
            except Exception as error:
                record(tag+'exception',traceback.format_exc(),False)
            finally: restore(r,f,m,offset)
    config=configparser.ConfigParser(); config.read(root/'yac.ini')
    ports=list(list_ports.comports())
    try:
        for section in config.sections():
            p=config[section]
            if not section.startswith('radio:') or not p.get('usb_identity'): continue
            matches=[port for port in ports if _usb_identity(port)==p['usb_identity']]
            if not matches: record(p['model'],'Not connected',False); continue
            matches.sort(key=lambda port:('Enhanced' not in port.description,'CI-V' not in port.description,port.device))
            port=matches[0].device
            r=RadioConnection(_open_serial(port,int(p['baud_rate']),serial),port,int(p['baud_rate']),p['protocol'],p['model_id'],p['model'],civ_address=int(p['civ_address'],0) if p.get('civ_address') else None)
            try: test(r)
            finally: r.close()
    finally:
        (root/'logs'/'radio-live-check.json').write_text(json.dumps(records,indent=2))


if __name__ == '__main__':
    main()
