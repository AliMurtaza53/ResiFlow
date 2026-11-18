"""Deterministic extra-exit screening without moving existing OD loading units."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
import igraph as ig
import shapely
from scipy.spatial import cKDTree
from resiflow.preprocess.network_connector_insertion import is_eligible_attachment_edge

class AccessIndex:
    def __init__(self, roads, nodes):
        self.roads=roads.reset_index(drop=True)
        pairs=self.roads[["from_id","to_id"]].astype(str)
        self.graph=ig.Graph.TupleList(pairs.itertuples(index=False,name=None),directed=False)
        self.graph.es["row"]=list(range(len(roads)))
        self.graph.es["metres"]=self.roads.geometry.length.tolist()
        self.position={n:i for i,n in enumerate(self.graph.vs["name"])}
        components=self.graph.connected_components()
        largest=max(range(len(components)),key=lambda k:len(components[k]))
        self.main={self.graph.vs[v]["name"] for v in components[largest]}
        cuts=self.graph.bridges()
        blocks=self.graph.copy();blocks.delete_edges(cuts)
        self.block=dict(zip(blocks.vs["name"],blocks.connected_components().membership))
        # Route access estimates without crossing a real mapped bridge/tunnel.
        sensitive=pd.Series(False,index=self.roads.index)
        if "faf5_class" in self.roads:
            sensitive |= pd.to_numeric(self.roads.faf5_class,errors="coerce").eq(41).fillna(False)
        if "road_label" in self.roads:
            sensitive |= self.roads.road_label.astype(str).str.strip().str.lower().isin(["bridge","tunnel","ferry"])
        for col in ("road_bridge","road_tunnel"):
            if col in self.roads:
                sensitive|=self.roads[col].astype(str).str.strip().str.lower().isin(["yes","true","1","1.0"])
        for col in ("bridge_fraction","tunnel_fraction"):
            if col in self.roads:sensitive|=pd.to_numeric(self.roads[col],errors="coerce").fillna(0).gt(0)
        self.sensitive=sensitive
        self.local=self.graph.copy()
        self.local.delete_edges(sorted(set(cuts)|set(np.flatnonzero(sensitive))))
        points=nodes.assign(node_id=nodes.node_id.astype(str)).drop_duplicates("node_id").set_index("node_id")
        self.names=[n for n in self.graph.vs["name"] if n in self.main and n in points.index]
        self.xy=np.array([(points.loc[n].geometry.x,points.loc[n].geometry.y) for n in self.names])
        self.tree=cKDTree(self.xy)
        self.points=points
        # Screen vectorially, then confirm individual supporting edges with the
        # shared eligibility function when candidates are evaluated.
        self.incident={}
        for idx,(a,b) in enumerate(pairs.itertuples(index=False,name=None)):
            self.incident.setdefault(a,[]).append(idx);self.incident.setdefault(b,[]).append(idx)

    def select(self, original, county_geometry, *, total=4, facility_points=None):
        anchors=sorted(set(str(n) for n in original)&self.main)
        if not anchors:return [],[{"reason":"no_valid_original_exit"}]
        nearby=set()
        for anchor in anchors:
            p=self.points.loc[anchor].geometry
            nearby.update(self.tree.query_ball_point((p.x,p.y),2000.))
        records=[]
        candidate=[]
        for idx in sorted(nearby,key=lambda i:self.names[i]):
            node=self.names[idx];p=self.points.loc[node].geometry
            row={"road_node":node,"x":p.x,"y":p.y}
            reason=None
            if node in anchors:reason="existing_exit"
            elif not county_geometry.covers(p):reason="outside_county"
            else:
                eligible=[r for r in self.incident[node] if not self.sensitive.iloc[r] and is_eligible_attachment_edge(self.roads.iloc[r])]
                if not eligible:reason="no_eligible_public_road_attachment"
                elif not any(self.block[node]==self.block[a] for a in anchors):reason="would_bypass_static_cut_edge"
                elif min(p.distance(self.points.loc[a].geometry) for a in anchors)<150:reason="too_close_to_existing_exit"
                elif facility_points is not None and (not len(facility_points) or min(p.distance(g) for g in facility_points)>300):reason="no_same_facility_reference_within_300m"
                else:row["supporting_edge"]=str(self.roads.iloc[eligible[0]].e_id)
            row["reason"]=reason or "pending_local_route"
            records.append(row)
            if reason is None:candidate.append(row)
        if not candidate:return [],records
        targets=[self.position[r["road_node"]] for r in candidate]
        distances=np.asarray(self.local.distances([self.position[a] for a in anchors],targets,weights="metres"))
        for j,row in enumerate(candidate):
            k=int(np.argmin(distances[:,j]));d=float(distances[k,j])
            row["anchor"]=anchors[k];row["access_path_m"]=d
            if not math.isfinite(d) or d>3000:row["reason"]="local_route_exceeds_3km_or_crosses_structure"
            else:row["reason"]="eligible"
        chosen=[];selected=list(anchors)
        while len(selected)<total:
            remaining=[r for r in candidate if r["reason"]=="eligible" and r not in chosen and
                       min(self.points.loc[r["road_node"]].geometry.distance(self.points.loc[n].geometry) for n in selected)>=150]
            if not remaining:break
            def rank(r):
                spread=min(self.points.loc[r["road_node"]].geometry.distance(self.points.loc[n].geometry) for n in selected)
                return (-spread/(1+r["access_path_m"]/3000),r["road_node"])
            row=min(remaining,key=rank)
            row["selection_order"]=len(selected)+1
            row["reason"]="selected"
            chosen.append(row);selected.append(row["road_node"])
        return chosen,records

    def access_geometry(self, base_geometry, anchor, destination):
        path=self.local.get_shortest_paths(self.position[anchor],to=self.position[destination],weights="metres",output="epath")[0]
        if not path:raise ValueError("Additional exit has no positive local access path")
        parts=[]
        for shape in [base_geometry]+[self.roads.iloc[self.local.es[e]["row"]].geometry for e in path]:
            parts.extend(list(shape.geoms) if shape.geom_type=="MultiLineString" else [shape])
        return shapely.geometry.MultiLineString([list(p.coords) for p in parts])
