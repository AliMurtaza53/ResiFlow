from pathlib import Path
import subprocess,json
R=Path("/scratch/akothaw/multimodal_hazard_data")
C=R/"code/ResiFlow_virtual_exemption_20261118"
OPS=R/"stage2_scripts/virtual_exemption_reruns_20261118"
OPS.mkdir(exist_ok=False)
(C/"SOURCE_REVISION.txt").write_text("4409abf\n")
jobs=[]
for scope in ["harvey15","conus"]:
 for arm in ["control","gateway"]:
  old=scope+"_connector_test2g_"+arm
  new=old+"_virtual_exempt"
  target=OPS/new;target.mkdir()
  template=(R/"stage2_scripts/connector_test2_gateway_full"/old/"recovery.slurm").read_text()
  template=template.replace(old,new)
  template=template.replace("CODE=$DATA/code/ResiFlow_gateway_full","CODE="+str(C))
  template=template.replace("BASE=$DATA/results/$VARIANT","BASE=$DATA/results/"+old)
  # Preserve the original OD source; template substitution affects control paths too.
  template=template.replace("/connector_test2_gateway_full/"+new+"/","/connector_test2_gateway_full/"+old+"/")
  # Isolate database, audit and log writes in the new operation directory.
  template=template.replace(str(R/"stage2_scripts/connector_test2_gateway_full"/old)+"/",str(target)+"/")
  lines=[]
  for line in template.splitlines():
   if line.startswith("profile_stage baseline_audit") or line.startswith("if grep -Eq") and "baseline_shortcuts" in line:continue
   if line.startswith("profile_stage edge_index"):continue
   lines.append(line)
   if line.startswith("export RESIFLOW_STAGE4_EXPORT_OD_PATHS"):
    lines.append("export RESIFLOW_GIT_COMMIT=4409abf")
   if line.startswith("profile_stage stage2_intersection"):
    lines.append(f'profile_stage verify_physical_state python "$CODE/scripts/diagnostics/verify_virtual_hazard_exemption.py" {old} {new} --results-root "$DATA/results"')
   if line.startswith("profile_stage stage3_postprocess"):
    lines.append(f'profile_stage verify_physical_damage python "$CODE/scripts/diagnostics/verify_virtual_hazard_exemption.py" {old} {new} --results-root "$DATA/results" --damage')
  script=target/"recovery.slurm";script.write_text("\n".join(lines)+"\n")
  subprocess.run(["bash","-n",str(script)],check=True)
  # No prior result or baseline alias may be overwritten.
  for p in [R/"results/disruption_analysis"/new,R/"results/damage_analysis"/new,R/"results/rerouting_analysis"/new,R/"results/base_scenario"/new]:
   assert not p.exists() and not p.is_symlink(),p
  assert (R/"results"/old/"edge_flows.gpq").is_file()
  # Store reviewed scripts first. Submission happens in a separate call.
  jobs.append({"old":old,"new":new,"script":str(script),"baseline":str(R/"results"/old),"source_revision":"4409abf"})
(OPS/"manifest.json").write_text(json.dumps(jobs,indent=2))
print(json.dumps(jobs,indent=2))
