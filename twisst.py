
import argparse
import itertools
import sys
import gzip
import operator
import ete3
import random
import numpy as np

np.seterr(divide='ignore', invalid="ignore")

verbose = False
##############################################################################################################################

def prod(iterable): return reduce(operator.mul, iterable, 1)

def sample(things, n = None, replace = False):
    if n == None: n = len(things)
    if replace == False: return random.sample(things,n)
    else: return [random.choice(things) for i in range(n)]

def randomComboGen(lists):
    while True: yield tuple(random.choice(l) for l in lists)

def getPrunedCopy(tree, leavesToKeep, preserve_branch_length):
    pruned = tree.copy("newick")
    ##prune function was too slow for big trees
    ## speeding up by first deleting all oter leaves
    for leaf in pruned.iter_leaves():
        if leaf.name not in leavesToKeep: leaf.delete(preserve_branch_length=preserve_branch_length)
    #and then prune to fix the root (not sure why this is necessary, but it is)
    #but at least it's faster than pruning the full tree
    pruned.prune(leavesToKeep, preserve_branch_length = preserve_branch_length)
    return pruned

def isRooted(tree): return len(tree.get_children()) == 2

#new version that does not do simplification, but has a few improvements
def weightTree(tree, taxa, taxonNames, nIts=None, topos=None, getDists = False):
    nTaxa = len(taxonNames)
    taxonDict = {}
    for x in range(nTaxa):
        for y in taxa[x]:
            taxonDict[y] = taxonNames[x]
    #we make a generator object for all combos
    #if there are more combos than Its, we need to make random samples
    nCombos = prod([len(t) for t in taxa])
    if nIts is None: nIts = nCombos
    if nIts >= nCombos:
        comboGenerator = itertools.product(*taxa)
        nIts = nCombos
    else: comboGenerator = randomComboGen(taxa)
    if not topos: topos=allTrees(taxonNames, [])
    #unique id for each topo
    topoIDs = [t.get_topology_id() for t in topos]
    counts = np.zeros(len(topos), dtype=int)
    if getDists: dists = np.zeros([nTaxa, nTaxa, len(topos)])
    for iteration in xrange(nIts):
        combo = comboGenerator.next()
        pruned = getPrunedCopy(tree, combo, preserve_branch_length = getDists)
        #rename leaves
        for leaf in pruned.iter_leaves(): leaf.name = taxonDict[leaf.name]
        #get pairwise dists if necessary
        if getDists:
            currentDists = np.zeros([nTaxa,nTaxa])
            for pair in itertools.combinations(range(nTaxa), 2):
                currentDists[pair[0],pair[1]] = currentDists[pair[1],pair[0]] = pruned.get_distance(taxonNames[pair[0]], taxonNames[pair[1]])
        #find topology match
        pruned.unroot()
        prunedID = pruned.get_topology_id()
        x = topoIDs.index(prunedID)
        counts[x] += 1
        if getDists: dists[:,:,x] += currentDists
    if getDists: meanDists = dists/counts
    else: meanDists = np.NaN
    return {"topos":topos,"weights":counts,"dists":meanDists}




#new version that does not do simplification, but has a few improvements
def weightTreeThreshold(tree, taxa, taxonNames, thresholdDict, topos=None, getDists = False):
    nTaxa = len(taxonNames)
    taxonDict = {}
    for x in range(nTaxa):
        for y in taxa[x]:
            taxonDict[y] = taxonNames[x]
    #make random combinations for sampling
    comboGenerator = randomComboGen(taxa)
    if not topos: allTrees(taxonNames, [])
    #unique id for each topo
    topoIDs = [t.get_topology_id() for t in topos]
    counts = np.zeros(len(topos), dtype=int)
    if getDists: dists = np.zeros([nTaxa, nTaxa, len(topos)])
    total=0
    while True:
        combo = comboGenerator.next()
        pruned = getPrunedCopy(tree, combo, preserve_branch_length = getDists)
        for leaf in pruned.iter_leaves(): leaf.name = taxonDict[leaf.name]
        #get pairwise dists if necessary
        if getDists: 
            currentDists = np.zeros([nTaxa,nTaxa])
            for pair in itertools.combinations(range(nTaxa), 2):
                currentDists[pair[0],pair[1]] = currentDists[pair[1],pair[0]] = pruned.get_distance(taxonNames[pair[0]], taxonNames[pair[1]])
        #find topology match
        pruned.unroot()
        prunedID = pruned.get_topology_id()
        x = topoIDs.index(prunedID)
        counts[x] += 1
        if getDists: dists[:,:,x] += currentDists
        total+=1
        #now check is we're under the threshold
        minCounts = np.minimum(counts,total-counts)
        if total not in thresholdDict or np.all(minCounts<=thresholdDict[total]): break
    if getDists: meanDists = dists/counts
    else: meanDists = np.NaN
    return {"topos":topos,"weights":counts,"dists":meanDists}




#a test version - this is designed to show how the values approach the truth with increasing iterations
def weightTreeEachIter(tree, taxa, taxonNames, nIts, topos):
    nTaxa = len(taxonNames)
    taxonDict = {}
    for x in range(nTaxa):
        for y in taxa[x]:
            taxonDict[y] = taxonNames[x]
    #we make a generator object for all combos
    #if there are more combos than Its, we need to make random samples
    nCombos = prod([len(t) for t in taxa])
    if nIts >= nCombos:
        comboGenerator = itertools.product(*taxa)
        nIts = nCombos
    else: comboGenerator = randomComboGen(taxa)
    #unique id for each topo
    topoIDs = [t.get_topology_id() for t in topos]
    topoIDsSet = set(topoIDs)
    counts = np.zeros([len(topos), nIts])
    for i in xrange(nIts):
        combo = comboGenerator.next()
        pruned = getPrunedCopy(tree, combo, preserve_branch_length = getDists)
        pruned.unroot()
        for leaf in pruned.iter_leaves(): leaf.name = taxonDict[leaf.name]
        #check for topology match
        prunedID = pruned.get_topology_id()
        x = topoIDs.index(prunedID)
        counts[x,i:] += 1
    total = np.sum(counts,0)
    weights =  counts/total
    return {"topos":topos,"counts":counts,"weights":weights}



''' below is a bunch of code for a potentially much faster method.
It first simplifies the tree, and weights each of the collapsed nodes
accordingly, and then does the weighting as before, but taking node weights into account.
It is super fast, and works well when trees are small, such that all combinations
can be tested, but when only a subset of combos are tested it is unreliable.
It seems to increase the variance dramatically, so in order to get a good result,
you need to test far more combos, so the efficiency improvement goes away. I couldn't
figure out if this makes sense, so I just dropped it for now.'''


def simplifyClade(node):
    #will Collapse a node, but change its branch length to the mean of all decendents
    #get lengths to all decendents
    leaves = node.get_leaves()
    leafDists = [1.*node.get_distance(leaf) for leaf in leaves]
    meanLeafDist = sum(leafDists)/len(leafDists)
    #now remove the children from this node
    for child in node.get_children():
        node.remove_child(child)
    #rename and add length
    node.name = leaves[0].name
    node.dist += meanLeafDist
    node.add_feature("weight", len(leaves))

'''If a leaf's nearest outgroup is a leaf from the same taxon, the inner leaf can be removed.
Example in the tree (C1,(B1,(B2,A1))); B2 can be removed, because A1's closest relative will stlill be from taxon B.
We remove B2, and correct branch lengths by moving the base downward (ie increase their  base), moving A1 upward,
and giving B1 the average length of B1 and B2.'''
def removeInnerLeaf(base, outerLeaf, innerNode, innerLeaf):
    #correct lengths
    relativeWeight = 1.*innerLeaf.weight/(innerLeaf.weight+outerLeaf.weight)
    base.dist += innerNode.dist * relativeWeight
    innerNode.dist = innerNode.dist * (1-relativeWeight)
    outerLeaf.dist = innerLeaf.dist*relativeWeight + outerLeaf.dist*(1-relativeWeight)
    #transfer weight
    outerLeaf.weight += innerLeaf.weight
    #delete
    innerLeaf.delete(preserve_branch_length=True)

'''If a pair of nodes both have two children, and those children are in the same taxa, then the nodes are twins.
We can remove one (along with it's children) after transfering the weights and averaging the lengths'''

'''I COULD NOT GET THIS STEP TO GIVE CORRECT DISTS - SO I GAVE UP'''

#def simplifyTwins(base, nodeA, nodeB, leafA0, leafA1, leafB0, leafB1):
    
    #weightA = leafA0.weight*leafA1.weight
    #weightB = leafB0.weight*leafB1.weight
    #weight01 = leafA0.weight*leafB1.weight
    #weight10 = leafA1.weight*leafB0.weight
    #totalWeight = weightA+weightB+weight01+weight10
    #relWeightA = weightA/totalWeight
    #relWeightB = weightB/totalWeight
    #relWeight01 = weight01/totalWeight
    #relWeight10 = weight10/totalWeight
        
    #dist0 = leafA0.dist*relWeightA + leafB0.dist*relWeightB + (leafA0.dist+nodeA.dist)*relWeight01 + (leafB0.dist+nodeB.dist)*relWeight10
    #dist1 = leafA1.dist*relWeightA + leafB1.dist*relWeightB + (leafA1.dist+nodeA.dist)*relWeight10 + (leafB1.dist+nodeB.dist)*relWeight01
    #distBase = (nodeA.dist+base.dist)*relWeightA + (nodeB.dist+base.dist)*relWeightB + base.dist*(relWeight01 + relWeight10)

    #leafA0.weight += leafB0.weight
    #leafA1.weight += leafB1.weight    

    #leafB0.delete()
    #leafB1.delete()
    #nodeB.delete()
    #base.delete()
    
    #nodeA.dist = distBase
    #leafA0.dist = dist0
    #leafA1.dist = dist1
    


def simplifyTree(tree,taxonDict):
    simpTree = tree.copy("newick")
    #remove all leaves that are not in the taxonDict
    simpTree.prune(taxonDict.keys(), preserve_branch_length = True)
    #we will check all nodes for monophyly
    for node in simpTree.traverse("levelorder"):
        #print "Checking node", node.name
        #check if node is in tree (not sure if this is necessary)
        if node not in simpTree: # probably not a necessary line if traversing from top down
            continue
        leafNames = node.get_leaf_names()
        #print len(leafNames), "leaves:"
        #print leafNames
        if len(leafNames) >= 2:
            sameTaxon = True
            #get taxon of first node, and then ckeck others
            taxon = taxonDict[leafNames[0]]
            for leafName in leafNames[1:]:
                if taxonDict[leafName] != taxon:
                    sameTaxon = False
                    break
            #if all same taxon, get mean branch length and collapse
            if sameTaxon:
                #print "simplifying node."
                simplifyClade(node)
                #print "new name:", node.name, "weight:", node.weight
        elif node.is_leaf():
            node.add_feature("weight", 1)
    #now we can do a second and third step.
    #Working up from tips, we remove any redundant leaves and transfer their weight and correct the lengths

    #We aslo check whether each node has twin pairs below it.
    #if so, we remove one and pass weights to the other, and average lengths.
    #this all gets run over and over until no new changes are made
    changed = True
    while changed:
        print simpTree.write()
        changed = False
        for node in simpTree.traverse("postorder"):
            cdn0 = node.get_children()
            if len(cdn0) == 2:
                if cdn0[0].is_leaf():
                    #print "testing", cdn0[0].name
                    cdn1 = cdn0[1].get_children()
                    if len(cdn1) == 2:
                        if cdn1[0].is_leaf() and taxonDict[cdn0[0].name] == taxonDict[cdn1[0].name]:
                            #print "removing", cdn1[0].name
                            removeInnerLeaf(base=node, outerLeaf=cdn0[0], innerNode=cdn0[1], innerLeaf=cdn1[0])
                            changed = True
                        elif cdn1[1].is_leaf() and taxonDict[cdn0[0].name] == taxonDict[cdn1[1].name]:
                            #print "removing", cdn1[1].name
                            removeInnerLeaf(base=node, outerLeaf=cdn0[0], innerNode=cdn0[1], innerLeaf=cdn1[1])
                            changed = True
                elif cdn0[1].is_leaf():
                    #print "testing", cdn0[1].name
                    cdn1 = cdn0[0].get_children()
                    if len(cdn1) == 2:
                        if cdn1[0].is_leaf() and taxonDict[cdn0[1].name] == taxonDict[cdn1[0].name]:
                            #print "removing", cdn1[0].name
                            removeInnerLeaf(base=node, outerLeaf=cdn0[1], innerNode=cdn0[0], innerLeaf=cdn1[0])
                            changed = True
                        elif cdn1[1].is_leaf() and taxonDict[cdn0[1].name] == taxonDict[cdn1[1].name]:
                            #print "removing", cdn1[1].name
                            removeInnerLeaf(base=node, outerLeaf=cdn0[1], innerNode=cdn0[0], innerLeaf=cdn1[1])
                            changed = True
                #if we get here the pair are both not leaves, but we can check if they're twins
                #This code only simplifies pair twins, but in theory all twins could be simplified'''
                '''I COULD NOT GET THIS FUNCTION TO GIVE FORRECT DISTS, SO I GAVE UP'''
                #elif len(node.get_leaves()) == 4:
                    ##print "Checking for twins"
                    #lvsA,lvsB = [child.get_leaves() for child in cdn0]
                    #if len(lvsA) == len(lvsB) == 2:
                        #taxaA = [taxonDict[lf.name] for lf in lvsA]
                        #taxaB = [taxonDict[lf.name] for lf in lvsB]
                        #if taxaA == taxaB:
                            ##print "removing", lvsB[0].name, "and", lvsB[1].name 
                            #simplifyTwins(base=node,nodeA=cdn0[0],nodeB=cdn0[1],leafA0=lvsA[0],leafA1=lvsA[1],leafB0=lvsB[0],leafB1=lvsB[1])
                            #changed = True
                        #elif taxaA[0] == taxaB[1] and taxaA[1] == taxaB[0]:
                            ##print "removing", lvsB[1].name, "and", lvsB[0].name 
                            #simplifyTwins(base=node,nodeA=cdn0[0],nodeB=cdn0[1],leafA0=lvsA[0],leafA1=lvsA[1],leafB0=lvsB[1],leafB1=lvsB[0])
                            #changed = True
    
    return simpTree


##a fake version of simpTree for testing, that does nothing but add weight to leaves
#def simplifyTree(tree,taxonDict):
    #simpTree = tree.copy("newick")
    ##remove all leaves that are not in the taxonDict
    #for node in simpTree.traverse("levelorder"):
        #if node.is_leaf():
            #node.add_feature("weight", 1)
    
    #return simpTree


#new version that does the tree simplification
def weightTreeSimp(tree, taxa, taxonNames, topos = None, getDists = False):
    assert isRooted(tree), "Tree must be rooted"
    nTaxa = len(taxonNames)
    nCombosTotal = prod([len(t) for t in taxa])
    taxonDict = {}
    for x in range(len(taxa)):
        for y in taxa[x]:
            taxonDict[y] = taxonNames[x]
    #simplify the tree
    simpTree = simplifyTree(tree, taxonDict)
    if verbose: print >> sys.stderr, simpTree
    leaves = simpTree.get_leaves()
    if verbose: print >> sys.stderr, "Simplified tree has", len(leaves), "leaves."
    leafNames = [leaf.name for leaf in leaves]
    leafWeights = dict(zip(leafNames, [leaf.weight for leaf in leaves]))
    #leafWeights = dict(zip(leafNames, [1]*len(leaves)))
    simpTaxa = [[t for t in taxon if t in leafNames] for taxon in taxa]
    #we make a generator object for all combos
    nCombos = prod([len(t) for t in simpTaxa])
    if verbose: print >> sys.stderr, "There are", nCombos, "combinations to test."
    comboGenerator = itertools.product(*simpTaxa)
    if not topos: allTrees(taxonNames, [])
    topoIDs = [t.get_topology_id() for t in topos]
    counts = np.zeros(len(topos), dtype=int)
    if getDists: dists = np.zeros([nTaxa, nTaxa, len(topos)])
    for combo in comboGenerator:
        comboWeight = prod(leafWeights[leafName] for leafName in combo)
        pruned = getPrunedCopy(simpTree, combo, preserve_branch_length = getDists)
        #generify pruned tree
        for leaf in pruned.iter_leaves(): leaf.name = taxonDict[leaf.name]
        
        #if getting dists - do that first before unrooting
        if getDists:
            currentDists = np.zeros([nTaxa,nTaxa])
            for pair in itertools.combinations(range(nTaxa), 2):
                currentDists[pair[0],pair[1]] = currentDists[pair[1],pair[0]] = pruned.get_distance(taxonNames[pair[0]], taxonNames[pair[1]])

        #check for topology match
        pruned.unroot()
        prunedID = pruned.get_topology_id()
        x = topoIDs.index(prunedID)
        counts[x] += comboWeight
        #get pairwise dists if necessary
        print pruned.write()
        if getDists: dists[:,:,x] += currentDists*comboWeight

    if getDists: meanDists = dists/counts
    else: meanDists = np.NaN

    return {"topos":topos,"weights":counts,"dists":meanDists}


def listToNwk(t):
    t = str(t)
    t = t.replace("[","(")
    t = t.replace("]",")")
    t = t.replace("'","")
    t += ";"
    return(t)

def allTopos(branches, _topos=None, _topo_IDs=None):
    if _topos is None or _topo_IDs is None:
        _topos = []
        _topo_IDs = set([])
    assert 4 <= len(branches) <= 8, "Please specify between 4 and 8 unique taxon names."
    #print "topos contains", len(_topos), "topologies."
    #print "current tree is:", branches 
    for x in range(len(branches)-1):
        for y in range(x+1,len(branches)):
            #print "Joining branch", x, branches[x], "with branch", y, branches[y]
            new_branches = list(branches)
            new_branches[x] = [new_branches[x],new_branches.pop(y)]
            #print "New tree is:", new_branches
            if len(new_branches) == 3:
                #print "Tree has three branches, so appending to topos."
                #now check that the topo doesn't match a topology already in trees, and if not add it
                t = ete3.Tree(listToNwk(new_branches))
                ID = t.get_topology_id()
                if ID not in _topo_IDs:
                    _topos.append(t)
                    _topo_IDs.add(ID)
            else:
                #print "Tree still unresolved, so re-calling function."
                _topos = allTopos(new_branches, _topos, _topo_IDs)
    #print _topo_IDs
    #print [t.write(format=9) for t in _topos]
    return(_topos)


#################################################################################################################################


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--treeFile", help="File containing tree(s) to analyse", action = "store")
    parser.add_argument("-w", "--weightsFile", help="Output file of all weights", action = "store")
    parser.add_argument("-D", "--distsFile", help="Output file of mean pairwise dists", action = "store", required = False)
    parser.add_argument("-o", "--topoFile", help="Output file of all topologies", action = "store", required = False)
    parser.add_argument("--outgroup", help="Outgroup for rooting", action = "store")
    parser.add_argument("--method", help="Tree sampling method", choices=["fixed", "threshold", "complete"], action = "store", default = "fixed")
    parser.add_argument("--iterations", help="Number of iterations for fixed partial sampling", type=int, action = "store", default = 400)
    parser.add_argument("--thresholdTable", help="Lookup_table_for_sampling_thresholds", action = "store")
    parser.add_argument("-g", "--group", help="Group name and individual names (separated by commas)", action='append', nargs="+", required = True, metavar=("name","[inds]"))
    parser.add_argument("--groupsFile", help="Optional file of sample names and groups", action = "store", required = False)
    parser.add_argument("--verbose", help="Verbose output", action="store_true")


    args = parser.parse_args()
    #args = parser.parse_args("-n 5 -t test.trees -o test.topos.txt -w test.weights.B.csv -g A a,b,c -g B d,e,f -g C g,h,i -g D j,k,l".split())

    if args.distsFile: getDists = True
    else: getDists = False

    method = args.method

    verbose = args.verbose

    #################################################################################################################################
    #parse taxa
    assert len(args.group) >= 4, "Please specify at least four groups."
    taxonNames = []
    taxa = []
    for g in args.group:
        taxonNames.append(g[0])
        if len(g) > 1: taxa.append(g[1].split(","))
        else: taxa.append([])
    
    if args.groupsFile:
        with open(args.groupsFile, "r") as gf: groupDict = dict([ln.split() for ln in gf.readlines()])
        for sample in groupDict.keys():
            try: taxa[taxonNames.index(groupDict[sample])].append(sample)
            except: pass
    
    nTaxa=len(taxa)
    
    assert min([len(t) for t in taxa]) >= 1, "Please specify at least one sample name per group."
    
    names = [t for taxon in taxa for t in taxon]
    namesSet = set(names)
    assert len(names) == len(namesSet), "Each sample should only be in one group."
    
    #get all topologies
    topos = allTopos(taxonNames, [])
    
    for topo in topos: print >> sys.stderr, topo


    #make a rooted set of topos, just for printing - this doesn't affect the analysis
    #toposRooted = [topo.copy("newick") for topo in topos]
    #for topo in toposRooted: topo.set_outgroup(taxonNames[-1])

    if args.topoFile:
        with open(args.topoFile, "w") as topoFile:
            topoFile.write("\n".join([t.write(format = 9) for t in topos]) + "\n")
    
    #################################################################################################################################
    
    # check method

    if method == "fixed":
        nIts = args.iterations
        if nIts >= prod([len(t) for t in taxa]):
            print >> sys.stderr, "Warning: number of iterations is equal or greater than possible combinations.\n"
            nIts = prod([len(t) for t in taxa])
            print >> sys.stderr, "This could be very slow. Use method 'complete' for fast(er) exhaustive sampling."
    
    elif method == "threshold":
        assert args.thresholdTable, "A threshold table must be provided using argument --thresholdTable."
        thresholdTableFileName = args.thresholdTable
        with open(thresholdTableFileName) as ttf:
            thresholdDict = dict([(int(tries),int(threshold)) for line in ttf.readlines() for tries,threshold in (line.split(),)])

    #################################################################################################################################
    ### file for weights

    if args.weightsFile:
       weightsFile = gzip.open(args.weightsFile, "w") if args.weightsFile.endswith(".gz") else open(args.weightsFile, "w")
    else: weightsFile = sys.stdout
    
    for x in range(len(topos)): weightsFile.write("#topo" + str(x+1) + " " + topos[x].write(format = 9) + "\n") 

    weightsFile.write("\t".join(["topo" + str(x+1) for x in range(len(topos))]) + "\n")

    ### file for lengths

    if getDists:
        if args.distsFile[-3:] == ".gz": distsFile = gzip.open(args.distsFile, "w")
        else: distsFile = open(args.distsFile, "w")
        for x in range(len(topos)):
            distsFile.write("\t".join(["topo" + str(x+1) + "_" + "_".join(pair) for pair in itertools.combinations(taxonNames,2)]) + "\t")
        distsFile.write("\n")

    ################################################################################################################################

    #open tree file
    
    if args.treeFile:
        treeFile = gzip.open(args.treeFile, "r") if args.treeFile.endswith(".gz") else open(args.treeFile, "r")
    else: treeFile = sys.stdin

    line = treeFile.readline()
    
    ################################################################################################################################

    n = 0

    while len(line) >= 1:

        try: tree = ete3.Tree(line)
        except: tree = None
        
        if tree:
            #remove unneccesary leaves (speeds up downstream steps)
            leafNamesSet = set([leaf.name for leaf in tree.get_leaves()])
            if namesSet != leafNamesSet:
                assert namesSet.issubset(leafNamesSet), "Named samples not present in tree."
                tree = getPrunedCopy(tree, leavesToKeep=names, preserve_branch_length=True)
            
            #root if necessary
            if args.outgroup: tree.set_outgroup(args.outgroup)
            
            if method == "fixed":
                weightsData = weightTree(tree=tree, taxa=taxa, taxonNames=taxonNames, nIts=nIts, topos=topos, getDists=getDists)
            elif method == "threshold":
                weightsData = weightTreeThreshold(tree=tree, taxa=taxa, taxonNames=taxonNames, thresholdDict=thresholdDict, topos=topos, getDists=getDists)
            elif method == "complete":
                weightsData = weightTreeSimp(tree=tree, taxa=taxa, taxonNames=taxonNames, topos=topos)
            weightsLine = "\t".join([str(x) for x in weightsData["weights"]])
        
            if getDists:
                distsByTopo = []
                for x in range(len(topos)):
                    distsByTopo.append("\t".join([str(round(weightsData["dists"][pair[0],pair[1],x], 4)) for pair in itertools.combinations(range(ntaxa), 2)]))
                distsLine = "\t".join(distsByTopo)    
        else:
            weightsLine = "\t".join(["NA"]*len(topos))
            if getDists: distsLine = "\t".join(["NA"]*len(topos)*len(itertools.combinations(range(nTaxa), 2)))
        
        weightsFile.write(weightsLine + "\n")
        if getDists: distsFile.write(distsLine + "\n")
        
        print >> sys.stderr, n
        n += 1
        line = treeFile.readline()

    treeFile.close()
    weightsFile.close()

    sys.exit()




#############################################################################################################################################



