"""Nova Laser Quote: shop-network quoting application. All prices in CAD."""
import io, json, math, os, sqlite3, uuid, zipfile, re, email
from email import policy
from email.parser import BytesParser
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import ezdxf
from ezdxf import path as ezpath
from shapely.geometry import LineString, Polygon, box, GeometryCollection
from shapely.ops import polygonize, unary_union
from shapely.affinity import rotate, translate
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('NOVA_DATA_DIR', str(ROOT/'data')))
DATA.mkdir(parents=True,exist_ok=True)
UPLOADS=DATA/'uploads'; UPLOADS.mkdir(exist_ok=True)
DB=DATA/'quotes.sqlite3'
app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=50*1024*1024
app.json.sort_keys=False

DEFAULT={
 'company':'Nova Machine Works Ltd.', 'currency':'CAD','machine':'Bodor P3 12 kW',
 'machine_hourly':150,'handling_min':1.0,'programming_min':4.0,'minimum_order':45,
 'markup_pct':30,'sheet_utilization_pct':100,'scrap_credit_pct':0,
 'rapid_speed_m_min':45,'pierce_overhead_sec':0.35,'gas_cost_hour':12,
 'materials':{
  'Mild steel':{'density':7850,'cost_per_kg':2.1,'thicknesses':{'1.5':{'speed_m_min':28,'pierce_sec':0.15},'3':{'speed_m_min':17,'pierce_sec':0.25},'6.35':{'speed_m_min':5,'pierce_sec':0.65},'12.7':{'speed_m_min':1.6,'pierce_sec':1.7}}},
  '304 stainless':{'density':8000,'cost_per_kg':6.5,'thicknesses':{'1.5':{'speed_m_min':25,'pierce_sec':0.2},'3':{'speed_m_min':11,'pierce_sec':0.4},'6.35':{'speed_m_min':3.0,'pierce_sec':1.1},'12.7':{'speed_m_min':0.9,'pierce_sec':2.5}}},
  '5052 aluminum':{'density':2680,'cost_per_kg':7.0,'thicknesses':{'1.5':{'speed_m_min':32,'pierce_sec':0.2},'3':{'speed_m_min':18,'pierce_sec':0.35},'6.35':{'speed_m_min':6,'pierce_sec':0.8},'12.7':{'speed_m_min':1.5,'pierce_sec':2}}}
 }
}

# v0.5: defaults are estimates, not measured production data.
COST_DEFAULTS={
 'labor_hourly':45.0,'programming_min_per_part':4.0,'setup_group_min':6.0,
 'sheet_width_mm':1219.2,'sheet_height_mm':2438.4,'nest_spacing_mm':3.175,'nest_margin_mm':6.35,
 'load_min_per_sheet':2.0,'unload_min_per_sheet':2.0,
 'part_removal_sec':8.0,'inspection_min_per_part_type':1.5,
 'nitrogen_cylinder_m3':9.0,'nitrogen_refill_cad':95.0,
 'oxygen_cylinder_m3':7.0,'oxygen_refill_cad':60.0,
 'cylinder_usable_pct':90.0,'cylinder_extra_cad_per_m3':0.0,
 'air_gas_cost_per_m3':0.0
}
GAUGE_INCHES={
 'steel':{'28':.0149,'27':.0164,'26':.0179,'25':.0209,'24':.0239,'23':.0269,'22':.0299,'21':.0329,'20':.0359,'19':.0418,'18':.0478,'17':.0538,'16':.0598,'15':.0673,'14':.0747,'13':.0897,'12':.1046,'11':.1196,'10':.1345},
 'stainless':{'28':.0156,'26':.0187,'24':.025,'22':.0313,'20':.0375,'18':.05,'16':.0625,'14':.0781,'12':.1094,'11':.125,'10':.1406},
 'aluminum':{'28':.0126,'26':.0159,'24':.0201,'22':.0253,'20':.032,'18':.0403,'16':.0508,'14':.0641,'12':.0808,'11':.0907,'10':.1019}}
STANDARD_THICKNESS_IN=sorted(set([.0126,.0149,.0156,.0159,.0179,.0187,.0209,.024,.030,.036,.040,.048,.050,.060,.063,.075,.080,.090,.100,.105,.120,.125,.135,.160,.1875,.25,.3125,.375,.5,.625,.75,.875,1.0,1.125,1.25]+[v for m in GAUGE_INCHES.values() for v in m.values()]))

MATERIAL_CATALOG={
 '5050 aluminum':(2680,'aluminum'), '5052 aluminum':(2680,'aluminum'),
 '6061 aluminum':(2700,'aluminum'), 'Hot rolled steel':(7850,'steel'),
 'Cold rolled steel':(7850,'steel'), '304 stainless':(8000,'stainless'),
 '316 stainless':(8000,'stainless'), 'Mild steel':(7850,'steel')}
STANDARD_THICKNESS_IN=[.0126,.0149,.0156,.0159,.0179,.0187,.0209,.024,.030,.036,.040,.048,.050,.060,.063,.075,.080,.090,.100,.105,.120,.125,.135,.160,.1875,.25,.3125,.375,.5,.625,.75,.875,1.0,1.125,1.25]
def gauge_label(mm,kind):
 inches=mm/25.4
 matches=[g for g,v in GAUGE_INCHES.get(kind,{}).items() if abs(v-inches)<.001]
 return (matches[0]+' ga / ' if matches else '')+f'{inches:.4f}"'
def material_kind(name,mat):
 return mat.get('category') or ('aluminum' if 'alum' in name.lower() else 'stainless' if 'stainless' in name.lower() else 'steel')
def new_profile(kind):
 return {'speed_m_min':1.0,'pierce_sec':0,'gas':'oxygen' if kind=='steel' else 'air',
  'gas_flow_m3_hour':0,'efficiency_pct':100,'source':'UNVERIFIED: enter measured Bodor cutting data',
  'cost_per_lb':{'steel':0.90,'aluminum':3.50,'stainless':5.00}.get(kind,0.0)}

def expand_materials(cfg):
 materials=cfg['materials']
 for name,(density,kind) in MATERIAL_CATALOG.items():
  if name not in materials:
   materials[name]={'density':density,'category':kind,'cost_per_kg':0,'supplier':'',
    'price_updated':'','sheet_prices':[],'description':'','thicknesses':{}}
  mat=materials[name];mat.setdefault('category',kind);mat.setdefault('description','')
  mat.setdefault('cost_per_kg',0)
  mat.setdefault('material_markup_pct',0.0)
  for inch in STANDARD_THICKNESS_IN:
   mm=round(inch*25.4,4);key=str(mm)
   if key not in mat['thicknesses']:
    mat['thicknesses'][key]=new_profile(kind)
  for t,profile in mat['thicknesses'].items():
   profile.setdefault('cost_per_lb',float(mat['cost_per_kg'])/2.2046226218 or {'steel':0.90,'aluminum':3.50,'stainless':5.00}.get(kind,0.0))
 for name,mat in materials.items():
  mat.setdefault('category',material_kind(name,mat));mat.setdefault('description','')
  mat.setdefault('material_markup_pct',0.0)
  for t,profile in mat.get('thicknesses',{}).items():
   profile.setdefault('cost_per_lb',float(mat.get('cost_per_kg',0))/2.2046226218 or {'steel':0.90,'aluminum':3.50,'stainless':5.00}.get(mat['category'],0.0))
 return cfg


# v1.0: conservative quoting-only reference profiles. Published speeds are NOT machine programs.
# References: https://www.senfenglasers.com/knowledge/12kw-fiber-laser-cutting-parameters.html
# https://alphacnc.com.au/wp-content/uploads/2024/05/Fiber-Laser-Cutter-Brochure-SwiftX-3015HS.pdf
# https://sbmlaser.com/our-services/cutting-parameters/
# Values below are conservative shop estimates based on lower published speed ranges.
# Piercing times and gas flows are estimates, not from the Bodor technics backup.
SPEED_KNOTS={
 'steel':[(0.5,35),(1,35),(2,28),(3,23),(4,18),(5,14),(6,10),(8,6),(10,2.0),(12,1.7),(14,1.5),(16,1.3),(20,1.1),(25,.7),(30,.35)],
 'stainless':[(0.5,35),(1,35),(2,28),(3,22),(4,18),(5,14),(6,12),(8,7),(10,5.5),(12,3.7),(16,1.7),(20,1.0),(25,.55)],
 'aluminum':[(0.5,30),(1,30),(2,23),(3,17),(5,12),(6,9),(8,5.5),(10,4.2),(12,2.5),(16,1.1),(20,.65),(25,.35)]}

def interpolated_speed(kind,mm):
 knots=SPEED_KNOTS[kind]
 if mm>knots[-1][0]:return None
 if mm<=knots[0][0]:return knots[0][1]
 for (a,va),(b,vb) in zip(knots,knots[1:]):
  if a<=mm<=b:
   f=(mm-a)/(b-a)
   return round(math.exp(math.log(va)*(1-f)+math.log(vb)*f),3)
 return None

def estimated_flow(gas,pressure_bar,nozzle_mm):
 # Choked-flow ideal-gas orifice model, Cd=0.65, 20 C, standard gas volume.
 # This is a theoretical nozzle-only approximation, NOT a measured machine gas flow.
 if gas=='air':return 0.0  # air is not costed, and its flow is not required for pricing
 gamma,R,rho={'nitrogen':(1.4,296.8,1.165),'oxygen':(1.395,259.8,1.331)}[gas]
 p=(pressure_bar+1.01325)*1e5;T=293.15;A=math.pi*(nozzle_mm/2000)**2
 mass=0.65*A*p*math.sqrt(gamma/(R*T))*(2/(gamma+1))**((gamma+1)/(2*(gamma-1)))
 return round(mass*3600/rho,2)

def seed_reference_profiles(cfg):
 if cfg.get('v10_reference_applied'):return cfg
 for name,mat in cfg.get('materials',{}).items():
  kind=material_kind(name,mat)
  if kind not in SPEED_KNOTS:continue
  for key,profile in mat.get('thicknesses',{}).items():
   src=str(profile.get('source','')).lower()
   # Never overwrite a user-verified or user-edited cutting profile.
   if src and not any(x in src for x in ('unverified','illustrative','example','enter measured','enter bodor')):continue
   mm=float(key);speed=interpolated_speed(kind,mm)
   if speed is None:
    profile.update(source='UNSUPPORTED / NO PUBLISHED 12 kW PRODUCTION SPEED: verify before quoting',reference_status='unsupported')
    continue
   gas='oxygen' if kind=='steel' and mm>=9 else 'air'
   if kind=='steel' and mm<9:gas='air'
   nozzle=(1.5 if mm<=2 else 2 if mm<=4 else 2.5 if mm<=6 else 3 if mm<=10 else 1.4 if kind=='steel' else 4)
   pressure=(0.7 if gas=='oxygen' else 12 if kind=='steel' else 14 if mm<=5 else 16)
   # conservative estimated cycle per pierce, increases with thickness
   pierce=round((0.35+0.12*mm+0.008*mm*mm) * (1.35 if kind=='steel' and mm>=9 else 1),2)
   # 80% of already-conservative straight-line feed to account for contours
   profile.update(speed_m_min=speed,pierce_sec=pierce,gas=gas,
      gas_pressure_bar=pressure,nozzle_mm=nozzle,gas_flow_m3_hour=estimated_flow(gas,pressure,nozzle),
      efficiency_pct=80,reference_status='estimated',
      source='ESTIMATE v1.0: conservative published 12 kW speed + interpolated thickness; pierce estimated; gas theoretical orifice (if cylinder). Verify on Bodor.')
 # Screenshot shows 3.175mm SS Big Graph cut speed 10 m/min, nozzle 3mm,
 # but selected list says Air while dialog says Nitrogen. Do not force gas/flow.
 for name in ('304 stainless','316 stainless'):
  mat=cfg['materials'].get(name)
  if not mat:continue
  prof=mat['thicknesses'].get('3.175')
  if prof and prof.get('reference_status')=='estimated':
   prof['speed_m_min']=10.0;prof['efficiency_pct']=80
   prof['source']='BODOR SCREENSHOT: 3.175 mm SS Big Graph speed 10 m/min; gas DISCREPANCY (list Air, dialog Nitrogen); pierce and gas estimates. Verify gas.' if name=='304 stainless' else 'ESTIMATE: 316 based on 304 Bodor screenshot 10 m/min; verify 316 performance and gas.'
   prof['reference_status']='partial_bodor' if name=='304 stainless' else 'estimated'
 cfg['v10_reference_applied']=True
 return cfg

def normalize_settings(cfg):
 if not cfg.get('v09_baseline_applied'):
  for name,mat in cfg.get('materials',{}).items():
   kind=material_kind(name,mat)
   base={'steel':0.90,'aluminum':3.50,'stainless':5.00}.get(kind)
   if base is not None:
    for profile in mat.get('thicknesses',{}).values():profile['cost_per_lb']=base
    mat['cost_per_kg']=base*2.2046226218
  cfg['v09_baseline_applied']=True
 # Migrate existing base programming minutes to the single per-part setting.
 if 'programming_min_per_part' not in cfg:
  cfg['programming_min_per_part']=cfg.get('programming_base_min',4.0)
 for old in ('programming_base_min','programming_per_contour_min','programming_per_meter_min'):
  cfg.pop(old,None)
 for k,v in COST_DEFAULTS.items():cfg.setdefault(k,v)
 expand_materials(cfg)
 seed_reference_profiles(cfg)
 for material,mat in cfg.get('materials',{}).items():
  mat.setdefault('material_markup_pct',0.0)
  mat.setdefault('price_updated','')
  mat.setdefault('supplier','')
  mat.setdefault('sheet_prices',[])
  for thickness,profile in mat.get('thicknesses',{}).items():
   if 'gas' not in profile:profile['gas']='oxygen' if material=='Mild steel' else 'air'
   profile.setdefault('gas_flow_m3_hour',0.0) # zero until measured; never invent cylinder consumption
   profile.setdefault('fine_speed_m_min',None)
   profile.setdefault('kerf_mm',None)
   profile.setdefault('gas_pressure_bar',None)
   profile.setdefault('nozzle_mm',None)
   profile.setdefault('preflow_sec',0.0)
   profile.setdefault('efficiency_pct',100.0)
   profile.setdefault('source','Unverified example')
 return cfg

def nonnegative_override(d,key,default):
 value=d.get(key)
 if value is None or value=='':return max(0.0,float(default))
 v=float(value)
 if not math.isfinite(v) or v<0 or v>100000:raise ValueError(key+' must be a nonnegative finite number')
 return v

def gas_unit_cost(s,gas):
 if gas=='air':return float(s['air_gas_cost_per_m3'])
 if gas not in ('nitrogen','oxygen'):raise ValueError('Invalid gas selection')
 usable=float(s[gas+'_cylinder_m3'])*float(s['cylinder_usable_pct'])/100
 if usable<=0:raise ValueError('Cylinder usable volume must be positive')
 return float(s[gas+'_refill_cad'])/usable+float(s['cylinder_extra_cad_per_m3'])

def estimate_line(line,g,s,mat,profile):
 if profile.get('reference_status')=='unsupported':raise ValueError('No reliable 12 kW production speed for this thickness; enter a verified profile before quoting')
 qty=int(line['quantity']);th=float(line['thickness_mm'])

 speed=nonnegative_override(line,'override_speed_m_min',profile['speed_m_min'])*float(profile.get('efficiency_pct',100))/100
 if speed<=0:raise ValueError('Cut speed must be positive')
 pierce=nonnegative_override(line,'override_pierce_sec',profile['pierce_sec'])
 cut=g['cut_length_mm']/1000/speed
 pierce_min=g['pierces']*(pierce+float(s['pierce_overhead_sec']))/60
 rapid=(g['pierces']*math.hypot(g['width_mm'],g['height_mm'])/1000/2)/float(s['rapid_speed_m_min'])
 machine_min=cut+pierce_min+rapid
 material_per=g['bounding_area_mm2']/1e6*(th/1000)*mat['density']*float(profile.get('cost_per_lb',float(mat['cost_per_kg'])/2.2046226218))*2.2046226218
 material_per*=1+float(mat.get('material_markup_pct',0))/100
 gas=profile['gas'];flow=float(profile['gas_flow_m3_hour'])
 gas_minutes=cut+pierce_min+g['pierces']*float(profile.get('preflow_sec',0))/60
 gas_per=gas_minutes/60*flow*gas_unit_cost(s,gas) # profile gas active time; flow requires calibration
 program=nonnegative_override(line,'programming_override_min',float(s['programming_min_per_part']))
 removal=nonnegative_override(line,'removal_override_min',qty*float(s['part_removal_sec'])/60)
 inspect=nonnegative_override(line,'inspection_override_min',s['inspection_min_per_part_type'])
 machine_cost=qty*machine_min/60*float(s['machine_hourly'])
 gas_cost=qty*gas_per
 material_cost=qty*material_per
 labor_cost=(program+removal+inspect)/60*float(s['labor_hourly'])
 return {'quantity':qty,'cycle_min':round(machine_min,3),'gas':gas,'gas_flow_m3_hour':flow,
  'material_cost':material_cost,'machine_cost':machine_cost,'gas_cost':gas_cost,'labor_cost':labor_cost,
  'programming_min':round(program,2),'removal_min':round(removal,2),'inspection_min':round(inspect,2),
  'cut_min':round(cut,3),'pierce_min':round(pierce_min,3),'rapid_min':round(rapid,3)}

def conn():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c

def init():
 with conn() as c:
  c.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, created TEXT NOT NULL, customer TEXT, part_name TEXT, payload TEXT NOT NULL)')
  c.execute('INSERT OR IGNORE INTO settings VALUES (1,?)',(json.dumps(DEFAULT),))
init()

def settings():
 with conn() as c: cfg=json.loads(c.execute('SELECT value FROM settings WHERE id=1').fetchone()['value'])
 # Add an explicit 1/8-inch cutting profile to older settings; initial figures are estimates.
 for mat in cfg.get('materials',{}).values():
  profiles=mat.get('thicknesses',{})
  if '3.175' not in profiles and '3' in profiles:
   profiles['3.175']={'speed_m_min':round(float(profiles['3']['speed_m_min'])*0.94,3),
                      'pierce_sec':round(float(profiles['3']['pierce_sec'])*1.08,3)}
 needs_migration=not cfg.get('v09_baseline_applied')
 normalized=normalize_settings(cfg)
 if needs_migration:
  with conn() as c:c.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(normalized),))
 return normalized

def lines_from_dxf(file_path):
 doc=ezdxf.readfile(str(file_path)); msp=doc.modelspace()
 # DXF $INSUNITS: 1=in, 2=ft, 4=mm, 5=cm, 6=m. Unitless assumed mm.
 unit=doc.header.get('$INSUNITS',4)
 scale={0:1,1:25.4,2:304.8,4:1,5:10,6:1000,8:0.0000254,9:0.0254,10:914.4,14:100}.get(unit)
 if scale is None:raise ValueError(f'Unsupported DXF drawing units ({unit}); convert drawing to mm.')
 segments=[]; unsupported={}; count=0
 def walk(ent,depth=0):
  nonlocal count
  if depth>6:raise ValueError('Too many nested block levels')
  count+=1
  if count>30000:raise ValueError('Too many DXF entities (limit 30,000)')
  typ=ent.dxftype()
  if typ=='INSERT':
   for e in ent.virtual_entities():walk(e,depth+1)
   return
  if typ not in ('LINE','ARC','CIRCLE','LWPOLYLINE','POLYLINE','ELLIPSE','SPLINE'):
   if typ not in ('TEXT','MTEXT','POINT','HATCH','DIMENSION','IMAGE','LEADER','XLINE','RAY'):
    unsupported[typ]=unsupported.get(typ,0)+1
   return
  try:
   p=ezpath.make_path(ent)
   verts=list(p.flattening(distance=0.08,segments=8))
  except Exception:
   unsupported[typ]=unsupported.get(typ,0)+1;return
  for a,b in zip(verts,verts[1:]):
   a=(a.x*scale,a.y*scale);b=(b.x*scale,b.y*scale)
   if math.dist(a,b)>1e-6:segments.append((a,b))
 for e in msp:walk(e)
 if not segments:raise ValueError('No supported cutting geometry found in DXF modelspace')
 if len(segments)>100000:raise ValueError('DXF too complex (over 100,000 segments)')
 return segments,unsupported,unit

def geometry(file_path):
 segments,unsupported,unit=lines_from_dxf(file_path)
 xs=[p[0] for seg in segments for p in seg];ys=[p[1] for seg in segments for p in seg]
 minx,maxx,miny,maxy=min(xs),max(xs),min(ys),max(ys)
 w=maxx-minx;h=maxy-miny
 length=sum(math.dist(a,b) for a,b in segments)
 # Polygonize closed contours; even-odd nesting determines net part area.
 polys=list(polygonize(unary_union([LineString([a,b]) for a,b in segments])))
 if polys:
  area=sum(p.area for p in polys)
  # polygonize produces individual faces; net material area = all faces (including enclosed holes)
  # with odd-even nesting: determine whether each face is inside another closed ring.
  rings=[]
  for p in polys:
   rings.append(p.exterior)
  # Determine solid face via nesting of exterior rings, with robust representative points.
  solid_area=0
  for p in polys:
   pt=p.representative_point()
   depth=sum(1 for r in rings if r.distance(pt)<1e-5 or __import__('shapely').geometry.Polygon(r).contains(pt))
   if depth%2==1:solid_area+=p.area
  area=solid_area
 else:area=0
 # Number of independent cut paths is estimated by connected components, snapped at 0.15mm.
 parent={}
 def root(x):
  parent.setdefault(x,x)
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 def join(a,b):
  ra,rb=root(a),root(b)
  if ra!=rb:parent[ra]=rb
 for a,b in segments:
  join((round(a[0]/0.15),round(a[1]/0.15)),(round(b[0]/0.15),round(b[1]/0.15)))
 pierces=len(set(root(x) for x in parent))
 # SVG geometry centered in viewBox; no raw DXF content inserted into HTML.
 sw=max(w,1);sh=max(h,1);stroke=max(sw,sh)/700
 paths=''.join(f'<line x1="{a[0]-minx:.3f}" y1="{maxy-a[1]:.3f}" x2="{b[0]-minx:.3f}" y2="{maxy-b[1]:.3f}"/>' for a,b in segments)
 svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-sw*.04:.3f} {-sh*.04:.3f} {sw*1.08:.3f} {sh*1.08:.3f}" preserveAspectRatio="xMidYMid meet"><g fill="none" stroke="#38bdf8" stroke-width="{stroke:.3f}">{paths}</g></svg>'
 warnings=[]
 if not polys:warnings.append('No closed contours detected; material area uses bounding rectangle.')
 if unsupported:warnings.append('Some unsupported DXF entities were ignored: '+', '.join(unsupported))
 if unit==0:warnings.append('DXF units unspecified; assumed millimetres. Verify dimensions.')
 warnings.append('Pierces are estimated from disconnected toolpaths, not CAM lead-ins.')
 return {'width_mm':round(w,3),'height_mm':round(h,3),'cut_length_mm':round(length,2),
         'pierces':pierces,'net_area_mm2':round(area,2),'bounding_area_mm2':round(w*h,2),
         'closed_contours':len(polys),'warnings':warnings,'svg':svg}

# Quoting nest: actual closed DXF contours, polygon collision, rotations, and bounded search.
# Not a CAM nest; no lead-ins, heat distortion, common-line cutting, or machine program.
def solid_outline(path):
 segments,unsupported,unit=lines_from_dxf(path)
 if unsupported:raise ValueError('Nesting requires supported DXF contours; unsupported entities: '+str(unsupported))
 edges=unary_union([LineString([a,b]) for a,b in segments])
 faces=list(polygonize(edges))
 if not faces:raise ValueError('Nesting requires closed contours. Fix open DXF geometry.')
 # polygonize yields non-overlapping faces. A face inside a hole has even winding depth.
 boundaries=[Polygon(f.exterior) for f in faces]
 solids=[]
 for i,f in enumerate(faces):
  point=f.representative_point()
  depth=sum(1 for j,b in enumerate(boundaries) if j!=i and b.contains(point) and b.area>f.area+0.01)
  if depth%2==0:solids.append(f)
 shape=unary_union(solids).buffer(0)
 if shape.is_empty or shape.area<0.01:raise ValueError('No valid part area for nesting')
 x0,y0,x1,y1=shape.bounds
 return translate(shape,xoff=-x0,yoff=-y0)

def nest_group(items, sheet_w, sheet_h, spacing=3.175, margin=6.35, max_parts=1200):
 from shapely.prepared import prep
 usable_w=sheet_w-2*margin;usable_h=sheet_h-2*margin
 if usable_w<=0 or usable_h<=0:raise ValueError('Sheet edge margin exceeds sheet size')
 pieces=[]
 for idx,shape,qty in items:
  if qty>max_parts or len(pieces)+qty>max_parts:raise ValueError('Nesting limited to 1200 pieces per material/thickness group; split the quotation')
  pieces.extend([(idx,shape)]*qty)
 pieces.sort(key=lambda x:-x[1].area)
 sheets=[];alloc={idx:0.0 for idx,_,_ in items};placements=[]
 # Polygon collision with a clearance buffer. Search in a staggered grid and several orientations.
 # Step bounded to avoid excessive computation; conservative compared to CAM optimization.
 for idx,base in pieces:
  variants=[]
  for angle in (0,90,180,270,45,135):
   r=rotate(base,angle,origin=(0,0));a,b,c,d=r.bounds
   r=translate(r,xoff=-a,yoff=-b)
   if c-a<=usable_w+1e-5 and d-b<=usable_h+1e-5:variants.append((angle,r,c-a,d-b))
  if not variants:raise ValueError('Part '+str(idx+1)+' exceeds sheet size with margins')
  chosen=None
  for sheet_no,placed in enumerate(sheets+[[]]):
   # First-fit bottom-left, candidate locations from existing edges plus coarse grid.
   candidates={(margin,margin)}
   for rec in placed:
    x,y,w,h=rec['bbox']
    for px,py in ((x+w+spacing,y),(x,y+h+spacing),(x+w+spacing,y+h+spacing)):
     candidates.add((round(px,2),round(py,2)))
   step=max(4.0,min(25.4,min(usable_w,usable_h)/35))
   # grid search lets curved profiles interlock where rectangular footprints overlap
   for yy in range(int(usable_h//step)+1):
    for xx in range(int(usable_w//step)+1):
     candidates.add((round(margin+xx*step,2),round(margin+yy*step,2)))
   for x,y in sorted(candidates,key=lambda p:(p[1],p[0])):
    for angle,r,w,h in variants:
     if x+w>sheet_w-margin+1e-5 or y+h>sheet_h-margin+1e-5:continue
     moved=translate(r,xoff=x,yoff=y)
     clearance=moved.buffer(spacing/2,join_style=2)
     if all(not clearance.intersects(q['clearance']) for q in placed):
      chosen=(sheet_no,{'index':idx,'angle':angle,'polygon':moved,'clearance':clearance,'bbox':(x,y,w,h)})
      break
    if chosen:break
   if chosen:break
  if chosen is None:raise ValueError('Nesting failed to place a part')
  sn,rec=chosen
  if sn==len(sheets):sheets.append([])
  sheets[sn].append(rec)
 # Cost allocation uses occupied sheet area by group, charged in full-sheet mode.
 total_area=sheet_w*sheet_h*len(sheets)
 footprint={idx:0 for idx,_,_ in items}
 for placed in sheets:
  for r in placed:footprint[r['index']]+=r['polygon'].area
 sum_area=sum(footprint.values())
 for idx in alloc:alloc[idx]=total_area*footprint[idx]/sum_area if sum_area else 0
 # SVG preview is schematic but uses the actual placed polygon paths.
 def path_d(poly):
  def ring(r):
   coords=list(r.coords)
   return 'M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in coords)+' Z'
  polys=list(poly.geoms) if hasattr(poly,'geoms') else [poly]
  return ' '.join(ring(p.exterior)+' '+ ' '.join(ring(h) for h in p.interiors) for p in polys if hasattr(p,'exterior'))
 views=[]
 for si,placed in enumerate(sheets[:8]):
  shapes=''.join(f'<path d="{path_d(r["polygon"])}" fill="hsl({(r["index"]*61+190)%360},65%,60%)" fill-opacity="0.7" stroke="#17445b" stroke-width="1" fill-rule="evenodd"/>' for r in placed)
  views.append(f'<svg viewBox="0 0 {sheet_w:.1f} {sheet_h:.1f}" xmlns="http://www.w3.org/2000/svg"><rect width="{sheet_w:.1f}" height="{sheet_h:.1f}" fill="#e5eef1" stroke="#54717c" stroke-width="3"/>{shapes}</svg>')
 return {'sheets':len(sheets),'allocated_area_mm2':alloc,'views':views,'placements':sum(map(len,sheets))}

def calculate(d,s):
 g=d['geometry'];qty=int(d['quantity']);assert 1<=qty<=100000

 mat=s['materials'][d['material']];th=str(d['thickness_mm']);profile=mat['thicknesses'][th]
 if profile.get('reference_status')=='unsupported':raise ValueError('No reliable 12 kW production speed for this thickness; enter a verified profile before quoting')
 if float(profile.get('cost_per_lb',0))<=0:raise ValueError('Enter a material cost CAD/lb before quoting')
 speed=float(d.get('override_speed_m_min') or profile['speed_m_min']);pierce=float(d.get('override_pierce_sec') or profile['pierce_sec'])
 if speed<=0:raise ValueError('Cut speed must be positive')
 # Charge by rectangular footprint and configurable utilization, not claimed true nesting.
 area_m2=g['bounding_area_mm2']/1e6
 material_per=area_m2*(float(d['thickness_mm'])/1000)*mat['density']*float(profile.get('cost_per_lb',float(mat['cost_per_kg'])/2.2046226218))*2.2046226218
 material_per*=1+float(mat.get('material_markup_pct',0))/100
 cut_min=g['cut_length_mm']/1000/speed
 pierce_min=g['pierces']*(pierce+s['pierce_overhead_sec'])/60
 # Rapid travel proxy: bounding box diagonal per pierce, capped to avoid wild estimates.
 rapid_min=(g['pierces']*math.hypot(g['width_mm'],g['height_mm'])/1000/2)/s['rapid_speed_m_min']
 machine_min=cut_min+pierce_min+rapid_min
 machine_per=machine_min/60*s['machine_hourly']
 gas_per=machine_min/60*s['gas_cost_hour']
 handling_per=s['handling_min']/60*s['machine_hourly']
 setup_total=s['programming_min']/60*s['machine_hourly']
 unit_cost=material_per+machine_per+gas_per+handling_per
 total_cost=unit_cost*qty+setup_total
 total=max(s['minimum_order'],total_cost*(1+s['markup_pct']/100))
 return {'qty':qty,'speed_m_min':round(speed,3),'material_per':round(material_per,2),'machine_per':round(machine_per,2),
 'gas_per':round(gas_per,2),'handling_per':round(handling_per,2),'setup_total':round(setup_total,2),
 'cut_min':round(cut_min,3),'pierce_min':round(pierce_min,3),'rapid_min':round(rapid_min,3),
 'cycle_min':round(machine_min,3),'unit_cost':round(unit_cost,2),'total_cost':round(total_cost,2),
 'total_price':round(total,2),'unit_price':round(total/qty,2),'markup_pct':s['markup_pct']}

@app.get('/')
def home():return render_template('index.html')
@app.get('/api/settings')
def get_settings():return jsonify(settings())
@app.post('/api/settings')
def save_settings():
 try:
  new=request.get_json(force=True)
  if not isinstance(new,dict):raise ValueError('Settings must be an object')
  for key in ['machine_hourly','handling_min','programming_min','minimum_order','markup_pct','rapid_speed_m_min','pierce_overhead_sec','gas_cost_hour']:
   if float(new[key])<0:raise ValueError(key+' cannot be negative')
  # Legacy sheet utilization setting retained for old saved data, no longer used in costing.
  if float(new['rapid_speed_m_min'])<=0:raise ValueError('Rapid speed must be positive')
  for mat in new['materials'].values():
   if float(mat['density'])<=0 or float(mat['cost_per_kg'])<0:raise ValueError('Invalid material price/density')
   for profile in mat['thicknesses'].values():
    if float(profile['speed_m_min'])<=0 or float(profile['pierce_sec'])<0:raise ValueError('Invalid cutting profile')
  new=normalize_settings(new)
  for key in COST_DEFAULTS:
   v=float(new[key])
   if not math.isfinite(v) or v<0:raise ValueError(key+' must be nonnegative')
  if float(new['cylinder_usable_pct'])>100:raise ValueError('Usable gas % cannot exceed 100')
  for mat in new['materials'].values():
   for profile in mat['thicknesses'].values():
    if profile['gas'] not in ('air','nitrogen','oxygen'):raise ValueError('Gas must be air, nitrogen or oxygen')
    if float(profile['gas_flow_m3_hour'])<0:raise ValueError('Gas flow must be nonnegative')
    if not 0<float(profile.get('efficiency_pct',100))<=100:raise ValueError('Efficiency must be between 0 and 100%')
    for optional in ('fine_speed_m_min','kerf_mm','gas_pressure_bar','nozzle_mm'):
     if profile.get(optional) not in (None,'') and float(profile[optional])<0:raise ValueError(optional+' cannot be negative')
    if float(profile.get('preflow_sec',0))<0:raise ValueError('Preflow must be nonnegative')
   for sheet in mat.get('sheet_prices',[]):
    if float(sheet['width_mm'])<=0 or float(sheet['length_mm'])<=0 or float(sheet['cost_cad'])<0:raise ValueError('Invalid sheet price record')
  with conn() as c:c.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(new),))
  return jsonify({'ok':True})
 except Exception as e:return jsonify({'error':str(e)}),400

# RFQ intake is a review aid: never treat extracted data as confirmed specifications.
RFQ_EXT={'.eml','.msg','.dxf','.pdf','.txt','.csv','.xlsx','.xls','.step','.stp','.dwg'}
def parse_rfq_file(name, content, results, depth=0):
 name=Path(name).name
 ext=Path(name).suffix.lower()
 if ext not in RFQ_EXT and ext!='.zip':return
 if len(content)>20*1024*1024:
  results['warnings'].append(f'{name}: file too large to inspect');return
 if ext=='.zip':
  if depth>0:return
  try:
   with zipfile.ZipFile(io.BytesIO(content)) as z:
    for item in z.infolist()[:150]:
     if item.is_dir() or item.file_size>20*1024*1024:continue
     if item.filename.startswith('__MACOSX/'):continue
     parse_rfq_file(item.filename,z.read(item),results,depth+1)
  except Exception as ex:results['warnings'].append(f'{name}: invalid ZIP ({ex})')
  return
 results['files'].append({'name':name,'type':ext,'size':len(content)})
 text=''
 try:
  if ext=='.eml':
   msg=BytesParser(policy=policy.default).parsebytes(content)
   results['emails'].append({'file':name,'from':str(msg.get('From','')),'subject':str(msg.get('Subject','')),'date':str(msg.get('Date',''))})
   for part in msg.walk():
    if part.is_multipart():continue
    blob=part.get_payload(decode=True) or b''
    filename=part.get_filename()
    if filename:
     parse_rfq_file(filename,blob,results,depth+1)
    elif part.get_content_type()=='text/plain':text+='\n'+blob.decode(part.get_content_charset() or 'utf-8',errors='replace')
  elif ext=='.msg':
   import extract_msg
   msg=extract_msg.Message(io.BytesIO(content))
   results['emails'].append({'file':name,'from':str(msg.sender or ''),'subject':str(msg.subject or ''),'date':str(msg.date or '')})
   text=str(msg.body or '')
   for att in msg.attachments:
    blob=att.data
    if isinstance(blob,bytes):parse_rfq_file(att.longFilename or att.shortFilename or 'attachment',blob,results,depth+1)
  elif ext in ('.txt','.csv'):text=content.decode('utf-8-sig',errors='replace')
  elif ext=='.pdf':
   from pypdf import PdfReader
   reader=PdfReader(io.BytesIO(content))
   text='\n'.join((page.extract_text() or '') for page in reader.pages[:20])
   if not text.strip():results['warnings'].append(f'{name}: scanned/image PDF; no text extracted')
  elif ext=='.xlsx':
   from openpyxl import load_workbook
   wb=load_workbook(io.BytesIO(content),read_only=True,data_only=True)
   for sheet in wb.worksheets[:5]:
    for row in sheet.iter_rows(max_row=250,max_col=20,values_only=True):
     text+=' '.join(str(v) for v in row if v is not None)+'\n'
  elif ext=='.dxf':
   token=uuid.uuid4().hex;p=UPLOADS/(token+'.dxf');p.write_bytes(content)
   try:
    g=geometry(p)
    results['drawings'].append({'file':name,'file_id':token,'hints':filename_hints(name),'width_mm':g['width_mm'],'height_mm':g['height_mm'],'cut_length_mm':g['cut_length_mm'],'pierces':g['pierces'],'warnings':g.get('warnings',[])})
   except Exception as ex:results['warnings'].append(f'{name}: DXF could not be analyzed: {ex}')
  elif ext in ('.dwg','.step','.stp','.xls'):
   results['warnings'].append(f'{name}: recognized, but geometry/text extraction not supported in this version')
 except ImportError as ex:results['warnings'].append(f'{name}: optional parser missing ({ex})')
 except Exception as ex:results['warnings'].append(f'{name}: parsing failed ({ex})')
 if text.strip():
  text=text[:30000]
  results['excerpts'].append({'file':name,'text':text[:4500]})
  results['_text']+='\n'+text

@app.post('/api/rfq/import')
def import_rfq():
 incoming=request.files.getlist('files')
 if not incoming:return jsonify({'error':'Drop at least one email, folder, or ZIP file'}),400
 results={'files':[],'emails':[],'drawings':[],'excerpts':[],'warnings':[],'_text':''}
 for f in incoming[:100]:
  if f.filename:
   parse_rfq_file(f.filename,f.read(),results)
 text=results.pop('_text')
 # Heuristic candidates; users must verify before quoting.
 mat=re.search(r'\b(304|316|5052|6061|mild steel|stainless steel|alumin(?:um|ium))\b',text,re.I)
 qty=re.search(r'\b(?:qty|quantity|quantities|pcs|pieces)\s*[:= -]?\s*(\d{1,6})\b',text,re.I)
 thick=re.search(r'\b(?:thickness|thk|thick|gauge)\s*[:= -]?\s*(\d+(?:\.\d+)?)\s*(mm|in|inch|\")?\b',text,re.I)
 results['candidates']={'material':mat.group(0) if mat else None,'quantity':int(qty.group(1)) if qty else None,'thickness':thick.group(0) if thick else None}
 results['warnings'].append('Extracted details are unverified. Confirm revisions, material, thickness and quantities against original RFQ.')
 return jsonify(results)


# Batch quoting: never trust geometry supplied by the browser. Re-read uploaded DXFs.
def filename_hints(name):
 stem=Path(name).stem
 mat=None
 if re.search(r'\b(ALUMINUM|ALUMINIUM|ALUM|5052|6061)\b',stem,re.I):mat='5052 aluminum'
 elif re.search(r'\b(STAINLESS|304|316|SS)\b',stem,re.I):mat='304 stainless'
 elif re.search(r'\b(STEEL|MILD|CRS|HRS)\b',stem,re.I):mat='Mild steel'
 q=re.search(r'\bQTY\s*[-_ ]*([0-9]{1,5})\b',stem,re.I)
 qty=int(q.group(1)) if q else None
 # Thickness is only inferred when clearly written next to material, or with an explicit unit.
 th=None
 m=re.search(r'(?<![\d.])(0?\.\d{2,4}|\d+(?:\.\d+)?)\s*(?:INCH|IN|\")?\s*(?:ALUMINUM|ALUMINIUM|ALUM|STEEL|STAINLESS|5052|6061|304|316)\b',stem,re.I)
 if m:
  n=float(m.group(1));th=round(n*25.4,4) if n<1 else None
 mm=re.search(r'(?<!\d)(\d+(?:\.\d+)?)\s*MM\b',stem,re.I)
 if mm:th=float(mm.group(1))
 return {'material':mat,'quantity':qty,'thickness_mm':th}

def batch_compute(lines,s):
 if not isinstance(lines,list) or not 1<=len(lines)<=150:raise ValueError('Select between 1 and 150 parts')
 out=[];groups={};sum_cost=0.0
 for line in lines:
  fid=str(line.get('file_id',''))
  if not re.fullmatch('[0-9a-f]{32}',fid):raise ValueError('Invalid DXF reference')
  path=UPLOADS/(fid+'.dxf')
  if not path.is_file():raise ValueError('DXF no longer available. Reimport the RFQ.')
  g=geometry(path);g.pop('svg',None)
  material=line['material'];th=str(line['thickness_mm']);qty=int(line['quantity'])
  if material not in s['materials']:raise ValueError('Unknown material: '+str(material))
  mat=s['materials'][material]
  if th not in mat['thicknesses']:raise ValueError('No cutting profile for '+material+' / '+th+' mm')
  if qty<1 or qty>100000:raise ValueError('Quantity must be 1–100000')
  profile=mat['thicknesses'][th]
  if float(profile.get('cost_per_lb',0))<=0:raise ValueError('Enter a verified material cost CAD/lb for '+material+' / '+th+' mm')
  detail=estimate_line(line,g,s,mat,profile)
  key=(material,th,detail['gas'])
  groups[key]=groups.get(key,0)+qty*g['bounding_area_mm2']
  cost=sum(detail[k] for k in ('material_cost','machine_cost','gas_cost','labor_cost'))
  sum_cost+=cost
  out.append({'file_id':fid,'filename':str(line.get('filename','part.dxf'))[:200],
   'material':material,'thickness_mm':th,'quantity':qty,'geometry':g,**detail,
   'extended_cost':round(cost,2),'warnings':g['warnings']})
 # Nest separately by material and thickness. Gas does not affect sheet grouping.
 grouped={}
 for i,x in enumerate(out):
  key=(x['material'],x['thickness_mm'])
  grouped.setdefault(key,[]).append((i,solid_outline(UPLOADS/(x['file_id']+'.dxf')),x['quantity']))
 sheets_by_group={};nest_previews=[];sheets=0
 sheet_w=float(s['sheet_width_mm']);sheet_h=float(s['sheet_height_mm'])
 spacing=float(s.get('nest_spacing_mm',3.175));margin=float(s.get('nest_margin_mm',6.35))
 if spacing<0 or margin<0:raise ValueError('Nesting spacing and margins must be nonnegative')
 for key,items in grouped.items():
  result=nest_group(items,sheet_w,sheet_h,spacing,margin)
  sheets_by_group[str(key)]=result['sheets'];sheets+=result['sheets']
  nest_previews.append({'material':key[0],'thickness_mm':key[1], 'sheets':result['sheets'],'svg_sheets':result['views']})
  for i,shape,qty in items:
   x=out[i];mat=s['materials'][x['material']];profile=mat['thicknesses'][x['thickness_mm']]
   allocated=result['allocated_area_mm2'][i]
   cost=allocated/1e6*(float(x['thickness_mm'])/1000)*float(mat['density'])*float(profile['cost_per_lb'])*2.2046226218
   cost*=1+float(mat.get('material_markup_pct',0))/100
   x['material_cost']=cost
   x['extended_cost']=cost+x['machine_cost']+x['gas_cost']+x['labor_cost']
 sum_cost=sum(x['extended_cost'] for x in out)
 load=nonnegative_override({},'load',s['load_min_per_sheet'])*sheets
 unload=nonnegative_override({},'unload',s['unload_min_per_sheet'])*sheets
 group_setup=nonnegative_override({},'setup',s['setup_group_min'])*len(groups)
 shared_cost=(load+unload+group_setup)/60*float(s['labor_hourly'])
 cost=sum_cost+shared_cost
 total=max(float(s['minimum_order']),cost*(1+float(s['markup_pct'])/100))
 remaining=round(total,2)
 for i,x in enumerate(out):
  allocation=round(total*x['extended_cost']/sum_cost,2) if sum_cost>0 else round(total/len(out),2)
  if i==len(out)-1:allocation=remaining
  else:remaining=round(remaining-allocation,2)
  x['line_total']=allocation;x['unit_price']=round(allocation/x['quantity'],4)
  for k in ('material_cost','machine_cost','gas_cost','labor_cost'):x[k]=round(x[k],2)
 return {'lines':out,'setup_cost':round(shared_cost,2),'total_cost':round(cost,2),
  'total_price':round(total,2),'markup_pct':s['markup_pct'],
  'total_pieces':sum(x['quantity'] for x in out),'sheets_estimated':sheets,
  'sheets_by_group':sheets_by_group,'nest_previews':nest_previews,'loading_min':round(load,2),
  'unloading_min':round(unload,2),'group_setup_min':round(group_setup,2),
  'cost_breakdown':{'material':round(sum(x['material_cost'] for x in out),2),
    'machine':round(sum(x['machine_cost'] for x in out),2),
    'gas':round(sum(x['gas_cost'] for x in out),2),
    'direct_labor':round(sum(x['labor_cost'] for x in out),2),
    'shared_handling_and_setup':round(shared_cost,2)},
  'warnings':['Contour placement is an estimating nest, not a validated production/CAM nest. Material charged by full sheets allocated by part area.',
   'Gas flow defaults to zero until measured; set m3/hour for each profile.',
   'Machine and labour rates must be configured to avoid double-counting.']}

@app.post('/api/batch/calculate')
def batch_calculate():
 try:
  d=request.get_json(force=True)
  return jsonify(batch_compute(d['lines'],settings()))
 except Exception as e:return jsonify({'error':str(e)}),400

@app.post('/api/batch/quotes')
def batch_save():
 try:
  d=request.get_json(force=True)
  customer=str(d.get('customer',''))[:200]
  result=batch_compute(d['lines'],settings())
  quote_id='NQ-'+datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:6].upper()
  s=settings();payload={'batch':True,'result':result,'settings_snapshot':{'company':s['company'],'machine':s['machine']}}
  with conn() as c:c.execute('INSERT INTO quotes VALUES (?,?,?,?,?)',(quote_id,datetime.now().isoformat(timespec='seconds'),customer,f"Batch ({len(result['lines'])} parts)",json.dumps(payload)))
  return jsonify({'id':quote_id,'pdf_url':'/api/quotes/'+quote_id+'/pdf','result':result})
 except Exception as e:return jsonify({'error':str(e)}),400

@app.post('/api/analyze')
def analyze():
 f=request.files.get('file')
 if not f or not f.filename.lower().endswith('.dxf'):return jsonify({'error':'Upload a .dxf file'}),400
 filename=secure_filename(f.filename) or 'part.dxf'; token=uuid.uuid4().hex
 p=UPLOADS/(token+'.dxf');f.save(p)
 try:
  g=geometry(p)
  # Avoid storing giant SVG in browser quote history.
  return jsonify({'file_id':token,'filename':filename,'geometry':g})
 except Exception as e:
  p.unlink(missing_ok=True);return jsonify({'error':str(e)}),400
@app.post('/api/calculate')
def calc():
 try:
  d=request.get_json(force=True)
  return jsonify(calculate(d,settings()))
 except Exception as e:return jsonify({'error':str(e)}),400
@app.post('/api/quotes')
def create_quote():
 try:
  d=request.get_json(force=True);s=settings()
  if len(str(d.get('customer','')))>200 or len(str(d.get('part_name','')))>200:raise ValueError('Text too long')
  result=calculate(d,s);id='NQ-'+datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:6].upper()
  d['result']=result;d['settings_snapshot']={'company':s['company'],'machine':s['machine']};d['geometry'].pop('svg',None)
  with conn() as c:c.execute('INSERT INTO quotes VALUES (?,?,?,?,?)',(id,datetime.now().isoformat(timespec='seconds'),d.get('customer',''),d.get('part_name',''),json.dumps(d)))
  return jsonify({'id':id,'result':result,'pdf_url':'/api/quotes/'+id+'/pdf'})
 except Exception as e:return jsonify({'error':str(e)}),400
@app.get('/api/quotes')
def quotes():
 with conn() as c:rows=c.execute('SELECT id,created,customer,part_name,payload FROM quotes ORDER BY created DESC LIMIT 200').fetchall()
 return jsonify([{'id':r['id'],'created':r['created'],'customer':r['customer'],'part_name':r['part_name'],'total':json.loads(r['payload'])['result']['total_price']} for r in rows])
@app.get('/api/quotes/<id>/pdf')
def pdf(id):
 with conn() as c:r=c.execute('SELECT * FROM quotes WHERE id=?',(id,)).fetchone()
 if not r:return jsonify({'error':'Quote not found'}),404
 d=json.loads(r['payload']);result=d['result'];s=d['settings_snapshot']
 if d.get('batch'):return batch_pdf(id,r,d)
 g=d['geometry']
 buff=io.BytesIO();doc=SimpleDocTemplate(buff,pagesize=letter,rightMargin=48,leftMargin=48,topMargin=48,bottomMargin=48)
 styles=getSampleStyleSheet();story=[]
 def para(v,style='Normal'):return Paragraph(escape(str(v)),styles[style])
 story.extend([para(s['company'],'Title'),Spacer(1,10),para('LASER CUTTING QUOTATION','Heading2'),Spacer(1,12),
 para('Quote: '+id),para('Date: '+r['created'][:10]),para('Customer: '+(r['customer'] or 'Not specified')),Spacer(1,16)])
 rows=[['Part','Material / thickness','Qty','Unit (CAD)','Total (CAD)'],
 [d.get('part_name') or d.get('filename') or 'Laser cut part',f"{d['material']} / {d['thickness_mm']} mm",str(result['qty']),f"${result['unit_price']:,.2f}",f"${result['total_price']:,.2f}"]]
 table=Table(rows,colWidths=[145,135,45,90,90],repeatRows=1)
 table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#17324b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.5,colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10)]))
 story.extend([table,Spacer(1,20),para(f"TOTAL: CAD ${result['total_price']:,.2f}",'Heading2'),Spacer(1,12),para('Part dimensions: '+str(g['width_mm'])+' x '+str(g['height_mm'])+' mm'),para('Machine: '+s['machine']),Spacer(1,12),para('Subject to drawing review, material availability, and confirmation of tolerances. Taxes, finishing, and delivery are excluded unless agreed otherwise.')])
 doc.build(story);buff.seek(0)
 return send_file(buff,mimetype='application/pdf',as_attachment=True,download_name=id+'.pdf')

def batch_pdf(id,r,d):
 result=d['result'];s=d['settings_snapshot'];buff=io.BytesIO()
 doc=SimpleDocTemplate(buff,pagesize=letter,rightMargin=35,leftMargin=35,topMargin=42,bottomMargin=42)
 styles=getSampleStyleSheet();story=[]
 def para(v,style='Normal'):return Paragraph(escape(str(v)),styles[style])
 story.extend([para(s['company'],'Title'),Spacer(1,8),para('LASER CUTTING QUOTATION','Heading2'),
  para('Quote: '+id),para('Date: '+r['created'][:10]),para('Customer: '+(r['customer'] or 'Not specified')),Spacer(1,14)])
 rows=[[para('Part'),para('Material / thickness'),para('Qty'),para('Unit CAD'),para('Total CAD')]]
 for line in result['lines']:
  rows.append([para(line['filename']),para(f"{line['material']} / {line['thickness_mm']} mm"),
   str(line['quantity']),f"${line['unit_price']:,.4f}",f"${line['line_total']:,.2f}"])
 t=Table(rows,colWidths=[190,140,35,70,75],repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#17324b')),
  ('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.3,colors.lightgrey),
  ('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8),
  ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
 story.extend([t,Spacer(1,16),para(f"TOTAL: CAD ${result['total_price']:,.2f}",'Heading2'),
  Spacer(1,10),para('Machine: '+s['machine']),
  para('Estimate only; subject to drawing, material and revision confirmation. No automatic nesting. Taxes, finishing and delivery excluded.')])
 doc.build(story);buff.seek(0)
 return send_file(buff,mimetype='application/pdf',as_attachment=True,download_name=id+'.pdf')

if __name__=='__main__':
 from waitress import serve
 host=os.environ.get('NOVA_HOST','0.0.0.0');port=int(os.environ.get('NOVA_PORT','8080'))
 print(f'Nova Laser Quote running on http://{host}:{port}')
 serve(app,host=host,port=port,threads=6)
