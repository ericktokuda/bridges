#!/usr/bin/env python3
"""Analysis of shortest paths in cities
"""

import argparse
import time
import os
from os.path import join as pjoin
import inspect

import sys
import numpy as np
from itertools import product
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
import igraph
import matplotlib.collections as mc
import pickle
import pandas as pd
from scipy.spatial import cKDTree
from enum import Enum

HOME = os.getenv('HOME')

ORIGINAL = 0
BRIDGE = 1
BRIDGEACC = 2

#############################################################
def info(*args):
    pref = datetime.now().strftime('[%y%m%d %H:%M:%S]')
    print(pref, *args, file=sys.stdout)

##########################################################
def parse_graphml(graphmlpath, cachedir, undir=True, samplerad=-1):
    """Read graphml file to igraph object and dump it to @pklpath
    It gets the major component, and simplify it (neither multi nor self loops)
    Receives the input path @graphmlpath and dump to @pklpath
    """
    info(inspect.stack()[0][3] + '()')
    f = os.path.splitext(os.path.basename(graphmlpath))[0]
    if samplerad > -1: f += '_rad{}'.format(samplerad)
    pklpath = pjoin(cachedir, f + '.pkl')

    if os.path.exists(pklpath):
        info('Loading existing file: {}'.format(pklpath))
        return pickle.load(open(pklpath, 'rb'))

    g = igraph.Graph.Read(graphmlpath)
    g.simplify(); info('g.is_simple():{}'.format(g.is_simple()))

    if undir:
        g.to_undirected()
        info('g.is_directed():{}'.format(g.is_directed()))

    g = sample_circle_from_graph(g, samplerad)

    g = g.components(mode='weak').giant()
    info('g.is_connected():{}'.format(g.is_connected()))

    g = add_lengths(g)
    g.vs['type'] = ORIGINAL
    g.es['type'] = ORIGINAL
    pickle.dump(g, open(pklpath, 'wb'))
    return g

##########################################################
def sample_circle_from_graph(g, radius):
    """Sample a random region from the graph
    """
    info(inspect.stack()[0][3] + '()')
    
    if radius < 0: return g
    coords = [(x, y) for x, y in zip(g.vs['x'], g.vs['y'])]
    c0 = coords[np.random.randint(g.vcount())]
    ids = get_points_inside_region(coords, c0, radius)
    todel = np.ones(g.vcount(), bool)
    todel[ids] = False
    g.delete_vertices(np.where(todel == True)[0])
    return g

##########################################################
def get_points_inside_region(coords, c0, radius):
    """Get points from @df within circle of center @c0 and @radius
    """
    info(inspect.stack()[0][3] + '()')
    kdtree = cKDTree(coords)
    inds = kdtree.query_ball_point(c0, radius)
    return sorted(inds)

##########################################################
def choose_bridge_endpoints(g, n):
    """Add @nnewedges to @g
    """
    info(inspect.stack()[0][3] + '()')
    nvertices = g.vcount()
    es = []
    for i in range(n):
        s, t = np.random.choice(nvertices, size=2, replace=False)
        es.append([s, t])
    return np.array(es)

##########################################################
def calculate_edge_len(g, srcid, tgtid):
    """Calculate edge length based on 'x' and 'y' attributes
    """
    src = np.array([float(g.vs[srcid]['x']), float(g.vs[srcid]['y'])])
    tgt = np.array([float(g.vs[tgtid]['x']), float(g.vs[tgtid]['y'])])
    return np.linalg.norm(tgt - src)

##########################################################
def add_edge(g, srcid, tgtid, eid):
    g.add_edge(srcid, tgtid, type=eid)
    g.es[g.ecount() - 1]['length'] = calculate_edge_len(g, srcid, tgtid)
    return g

##########################################################
def add_bridge_access(g, edge, coordstree, spacing, nnearest):
    """Add @eid bridge access in @g
    """
    info(inspect.stack()[0][3] + '()')
    coords = coordstree.data
    srcid, tgtid = edge
    src = coords[srcid]
    tgt = coords[tgtid]
    v = tgt - src
    vnorm = np.linalg.norm(v)
    versor = v / vnorm

    d = spacing

    lastpid = srcid
    while d < vnorm:
        p = src + versor * d
        params = {'type':BRIDGE, 'x':p[0], 'y':p[1]}
        g.add_vertex(p, **params) # new vertex in the bridge
        
        newvid = g.vcount() - 1
        g = add_edge(g, lastpid, newvid, BRIDGE)
        vlast = g.vcount() - 1
        g.vs[vlast]['x'] = p[0]
        g.vs[vlast]['y'] = p[1]
        _, ids = coordstree.query(p, nnearest + 2)
        
        for i, id in enumerate(ids): # create accesses
            if i >= nnearest: break
            if id == srcid or id == tgtid: continue
            g = add_edge(g, vlast, id, BRIDGEACC)

        d += spacing

    g = add_edge(g, lastpid, tgtid, BRIDGE)

##########################################################
def partition_edges(g, es, spacing, nnearest=1):
    """Partition bridges spaced by @spacing and each new vertex is connected to
    the nearest node
    """
    info(inspect.stack()[0][3] + '()')
    nvertices = g.vcount()
    nedges = g.ecount()
    coords = [[x, y] for x, y in zip(g.vs['x'], g.vs['y'])]
    coordstree = cKDTree(coords)

    for edge in es:
        add_bridge_access(g, edge, coordstree, spacing, nnearest)
    return g
       
##########################################################
def add_lengths(g):
    """Add lengths to the graph
    """
    info(inspect.stack()[0][3] + '()')
    for i, e in enumerate(g.es()):
        srcid, tgtid = e.source, e.target
        g.es[i]['length'] = calculate_edge_len(g, srcid, tgtid)
    return g

##########################################################
def calculate_avg_path_length(g, weighted=False, srctgttypes=None):
    """Calculate avg path length of @g.
    Calling all at once, without the loop on the vertices, it crashes
    for large graphs
    """
    info(inspect.stack()[0][3] + '()')
    if g.is_directed():
        raise Exception('This method considers an undirected graph')

    if weighted:
        def sho(i, tgtids):
            return np.array(g.shortest_paths(source=vids[i],
                target=vids[i+1:],
                weights=g.es['length'],
                mode='ALL'))
    else:
        def sho(i, tgtids):
            return np.array(g.shortest_paths(source=vids[i],
                target=vids[i+1:],
                mode='ALL'))

    dsum = 0; d2sum = 0
    if srctgttypes == None:
        vids = list(range(g.vcount()))
    else: # consider src and tget of particular types
        vids = np.where(np.array(g.vs['type']) == srctgttypes)[0]
    
    for i, srcid in enumerate(range(len(vids))): #Assuming undirected graph
        aux = sho(i, vids)
        dsum += np.sum(aux)
        d2sum += np.sum(np.square(aux))

    ndists = int((g.vcount() * (g.vcount()-1)) / 2) # diagonal
    distmean = dsum / ndists
    diststd = np.sqrt(( d2sum - (dsum**2)/ndists ) / ndists)
    return distmean, diststd

##########################################################
def analyze_increment_of_random_edges(gin, nnewedges, spacing, outcsv):
    """Analyze random increment of n edges to @g for each value n in @nnewedges
    """
    info(inspect.stack()[0][3] + '()')
    g = gin.copy()
    data = [] # average path lengths
    g.es['type'] = ORIGINAL
    prev = 0

    for n in [0] + nnewedges:
        nnew = n - prev
        info('Adding {} edges'.format(nnew))
        es = choose_bridge_endpoints(g, nnew)
        g = partition_edges(g, es, spacing, nnearest=1)

        etypes = np.array(g.es['type'])
        
        meanw, stdw = calculate_avg_path_length(g,
                weighted=True,
                srctgttypes=None,)
        
        bv = g.betweenness()
        betwvmean, betwvstd = np.mean(bv), np.std(bv)

        data.append([g.vcount(), g.ecount(),
            n,
            len(np.where(etypes == BRIDGEACC)[0]),
            meanw, stdw,
            betwvmean, betwvstd,
            ])
        prev = n

    cols = 'nvertices,nedges,nbridges,naccess,' \
            'avgpathlen,stdpathlen,betwvmean,betwvstd'.\
            split(',')
    df = pd.DataFrame(data, columns=cols)
    df.to_csv(outcsv, index=False)
    info('df:{}'.format(df))
    return g

##########################################################
def hex2rgb(hexcolours, normalized=False, alpha=None):
    rgbcolours = np.zeros((len(hexcolours), 3), dtype=int)
    for i, h in enumerate(hexcolours):
        rgbcolours[i, :] = np.array([int(h.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)])

    if alpha != None:
        aux = np.zeros((len(hexcolours), 4), dtype=float)
        aux[:, :3] = rgbcolours / 255
        aux[:, -1] = .7 # alpha
        rgbcolours = aux
    elif normalized:
        rgbcolours = rgbcolours.astype(float) / 255

    return rgbcolours

##########################################################
def plot_map(g, outdir):
    """Plot map g, according to 'type' attrib both in vertices and in edges
    """
    
    info(inspect.stack()[0][3] + '()')
    nrows = 1;  ncols = 1
    figscale = 5
    fig, axs = plt.subplots(nrows, ncols, squeeze=False,
                figsize=(ncols*figscale, nrows*figscale))
    lines = np.zeros((g.ecount(), 2, 2), dtype=float)
    
    ne = g.ecount()
    palettehex = plt.rcParams['axes.prop_cycle'].by_key()['color']
    palettergb = hex2rgb(palettehex, normalized=True, alpha=0.6)

    ecolours = [ palettergb[i, :] for i in g.es['type']]

    for i, e in enumerate(g.es()):
        srcid = int(e.source)
        tgtid = int(e.target)

        lines[i, 0, :] = [g.vs[srcid]['x'], g.vs[srcid]['y']]
        lines[i, 1, :] = [g.vs[tgtid]['x'], g.vs[tgtid]['y']]

    lc = mc.LineCollection(lines, colors=ecolours, linewidths=figscale*.1)
    axs[0, 0].add_collection(lc)
    axs[0, 0].autoscale()

    
    coords = np.array([[float(x), float(y)] for x, y in zip(g.vs['x'], g.vs['y'])])

    # vids = np.where(np.array(g.vs['type']) == ORIGINAL)[0]
    # axs[0, 0].scatter(coords[vids, 0], coords[vids, 1])

    vids = np.where(np.array(g.vs['type']) == BRIDGE)[0]
    axs[0, 0].scatter(coords[vids, 0], coords[vids, 1], s=figscale*.1, c='k')

    plt.savefig(pjoin(outdir, 'map.pdf'))

##########################################################
def main():
    info(inspect.stack()[0][3] + '()')
    t0 = time.time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graphmlpath', required=True, help='Path to the map in graphml')
    parser.add_argument('--samplerad', default=-1, type=float, help='Sample radius')
    parser.add_argument('--outdir', default='/tmp/out/', help='Output directory')
    args = parser.parse_args()

    cachedir = './data/'
    if not os.path.isdir(args.outdir): os.mkdir(args.outdir)
    if not os.path.isdir(cachedir): os.mkdir(cachedir)

    np.random.seed(0)
    outcsv = pjoin(args.outdir, 'results.csv')
    nnewedges = sorted([1])
    maxnedges = np.max(nnewedges)
    spacing = 0.005

    g = parse_graphml(args.graphmlpath, cachedir, undir=True,
            samplerad=args.samplerad)
    # mean1, std1 = calculate_avg_path_length(g, weighted=True)

    # s = np.array(g.shortest_paths(weights=g.es['length'])).flatten()
    # inds = np.where(s == 0)[0][:g.vcount()]
    # all = np.delete(s, inds)
    # info('CORRECT mean:{}, std:{}'.format(np.mean(all), np.std(s)))

    
    # l2 = calculate_avg_path_length(g, weighted=True)
    # return
    info('nvertices: {}'.format(g.vcount()))
    info('nedges: {}'.format(g.ecount()))

    g = analyze_increment_of_random_edges(g, nnewedges, spacing, outcsv)
    plot_map(g, args.outdir)
    info('Elapsed time:{}'.format(time.time()-t0))

##########################################################
if __name__ == "__main__":
    main()
