# training of the new CRF model
# denseCRF [category] [configuration]

##################some import
import matplotlib
matplotlib.use("Agg") #if run outside ipython do not show any figure
from database import *
from multiprocessing import Pool
import util
import pyrHOG2
#import pyrHOG2RL
import extra
import VOCpr
import model
import time
import copy
import itertools
import sys
import crf3

########################## load configuration parametes

print "Loading defautl configuration config.py"
from config import * #default configuration      

if len(sys.argv)>2: #specific configuration
    print "Loading configuration from %s"%sys.argv[2]
    import_name=sys.argv[2]
    exec "from config_%s import *"%import_name
    
cfg.cls=sys.argv[1]
testname=cfg.testpath+cfg.cls+("%d"%cfg.numcl)+"_"+cfg.testspec
cfg.useRL=False#for the moment
cfg.show=False
cfg.auxdir=""
cfg.numhyp=5
cfg.rescale=True#False
cfg.numneg= 10
bias=100
cfg.bias=bias
#just for a fast test
cfg.maxpos = 500
cfg.maxneg = 50
cfg.maxexamples = 10000
cfg.maxtest = 100
parallel=True
cfg.show=False
cfg.neginpos=False
localshow=True
numcore=4
notreg=1

########################load training and test samples
if cfg.db=="VOC":
    if cfg.year=="2007":
        trPosImages=getRecord(VOC07Data(select="pos",cl="%s_trainval.txt"%cfg.cls,
                        basepath=cfg.dbpath,#"/home/databases/",
                        usetr=True,usedf=False),cfg.maxpos)
        trPosImagesNoTrunc=getRecord(VOC07Data(select="pos",cl="%s_trainval.txt"%cfg.cls,
                        basepath=cfg.dbpath,#"/home/databases/",
                        usetr=False,usedf=False),cfg.maxpos)
        trNegImages=getRecord(VOC07Data(select="neg",cl="%s_trainval.txt"%cfg.cls,
                        basepath=cfg.dbpath,#"/home/databases/",#"/share/ISE/marcopede/database/",
                        usetr=True,usedf=False),cfg.maxneg)
        trNegImagesFull=getRecord(VOC07Data(select="neg",cl="%s_trainval.txt"%cfg.cls,
                        basepath=cfg.dbpath,usetr=True,usedf=False),5000)
        #test
        tsPosImages=getRecord(VOC07Data(select="pos",cl="%s_test.txt"%cfg.cls,
                        basepath=cfg.dbpath,#"/home/databases/",#"/share/ISE/marcopede/database/",
                        usetr=True,usedf=False),cfg.maxtest)
        tsNegImages=getRecord(VOC07Data(select="neg",cl="%s_test.txt"%cfg.cls,
                        basepath=cfg.dbpath,#"/home/databases/",#"/share/ISE/marcopede/database/",
                        usetr=True,usedf=False),cfg.maxneg)
        tsImages=numpy.concatenate((tsPosImages,tsNegImages),0)
        tsImagesFull=getRecord(VOC07Data(select="all",cl="%s_test.txt"%cfg.cls,
                        basepath=cfg.dbpath,
                        usetr=True,usedf=False),5000)

elif cfg.db=="buffy":
    trPosImages=getRecord(Buffy(select="all",cl="trainval.txt",
                    basepath=cfg.dbpath,
                    trainfile="buffy/",
                    imagepath="buffy/images/",
                    annpath="buffy/",
                    usetr=True,usedf=False),cfg.maxpos)
    trPosImagesNoTrunc=trPosImages
    trNegImages=getRecord(DirImages(imagepath=cfg.dbpath+"INRIAPerson/train_64x128_H96/neg/"),cfg.maxneg)
    trNegImagesFull=trNegImages
    #test
    tsPosImages=getRecord(Buffy(select="all",cl="test.txt",
                    basepath=cfg.dbpath,
                    trainfile="buffy/",
                    imagepath="buffy/images/",
                    annpath="buffy/",
                    usetr=True,usedf=False),cfg.maxtest)
    tsImages=tsPosImages#numpy.concatenate((tsPosImages,tsNegImages),0)
    tsImagesFull=tsPosImages

########################compute aspect ratio and dector size 
name,bb,r,a=extractInfo(trPosImages)
trpos={"name":name,"bb":bb,"ratio":r,"area":a}
import scipy.cluster.vq as vq
numcl=cfg.numcl
perc=cfg.perc#10
minres=10
minfy=3
minfx=3
#maxArea=25*(4-cfg.lev[0])
maxArea=15*(4-cfg.lev[0])
usekmeans=False

sr=numpy.sort(r)
spl=[]
lfy=[];lfx=[]
cl=numpy.zeros(r.shape)
for l in range(numcl):
    spl.append(sr[round(l*len(r)/float(numcl))])
spl.append(sr[-1])
for l in range(numcl):
    cl[numpy.bitwise_and(r>=spl[l],r<=spl[l+1])]=l
for l in range(numcl):
    print "Cluster same number",l,":"
    print "Samples:",len(a[cl==l])
    #meanA=numpy.mean(a[cl==l])/16.0/(0.5*4**(cfg.lev[l]-1))#4.0
    meanA=numpy.mean(a[cl==l])/16.0/(4**(cfg.lev[l]-1))#4.0
    print "Mean Area:",meanA
    sa=numpy.sort(a[cl==l])
    #minA=numpy.mean(sa[len(sa)/perc])/16.0/(0.5*4**(cfg.lev[l]-1))#4.0
    minA=numpy.mean(sa[int(len(sa)*perc)])/16.0/(4**(cfg.lev[l]-1))#4.0
    print "Min Area:",minA
    aspt=numpy.mean(r[cl==l])
    print "Aspect:",aspt
    if minA>maxArea:
        minA=maxArea
    #minA=10#for bottle
    if aspt>1:
        fx=(max(minfx,numpy.sqrt(minA/aspt)))
        fy=(fx*aspt)
    else:
        fy=(max(minfy,numpy.sqrt(minA*(aspt))))
        fx=(fy/(aspt))        
    print "Fy:%.2f"%fy,"~",round(fy),"Fx:%.2f"%fx,"~",round(fx)
    lfy.append(round(fy))
    lfx.append(round(fx))
    print

#raw_input()

cfg.fy=lfy#[7,10]#lfy
cfg.fx=lfx#[11,7]#lfx
# the real detector size would be (cfg.fy,cfg.fx)*2 hog cells


############################ initialize positive using cropped bounidng boxes
check = False
import pylab as pl
dratios=numpy.array(cfg.fy)/numpy.array(cfg.fx)
hogp=[[] for x in range(cfg.numcl)]
hogpcl=[]

#from scipy.ndimage import zoom
from extra import myzoom as zoom
for im in trPosImagesNoTrunc: # for each image

    aim=util.myimread(im["name"])  
    for bb in im["bbox"]: # for each bbox (y1,x1,y2,x2)
        imy=bb[2]-bb[0]
        imx=bb[3]-bb[1]
        cropratio= imy/float(imx)
        #select the right model based on aspect ratio
        idm=numpy.argmin(abs(dratios-cropratio))
        crop=aim[max(0,bb[0]-imy/cfg.fy[idm]/2):min(bb[2]+imy/cfg.fy[idm]/2,aim.shape[0]),max(0,bb[1]-imx/cfg.fx[idm]/2):min(bb[3]+imx/cfg.fx[idm]/2,aim.shape[1])]
        #crop=extra.getfeat(aim,abb[0]-imy/(cfg.fy[idm]*2),bb[2]+imy/(cfg.fy[idm]*2),bb[1]-imx/(cfg.fx[idm]*2),bb[3]+imx/(cfg.fx[idm]*2))
        imy=crop.shape[0]
        imx=crop.shape[1]
        zcim=zoom(crop,(((cfg.fy[idm]*2+2)*8/float(imy)),((cfg.fx[idm]*2+2)*8/float(imx)),1),order=1)
        hogp[idm].append(numpy.ascontiguousarray(pyrHOG2.hog(zcim)).flatten())
        #hogpcl.append(idm)
        if check:
            print "Aspect:",idm,"Det Size",cfg.fy[idm]*2,cfg.fx[idm]*2,"Shape:",zcim.shape
            pl.figure(1,figsize=(20,5))
            pl.clf()
            pl.subplot(1,3,1)
            pl.imshow(aim,interpolation="nearest")            
            pl.subplot(1,3,2)
            pl.imshow(zcim,interpolation="nearest")
            pl.subplot(1,3,3)
            import drawHOG
            imh=drawHOG.drawHOG(hogp[-1])
            pl.imshow(imh,interpolation="nearest")
            pl.draw()
            pl.show()
            raw_input()
for l in range(cfg.numcl):
    print "Aspect",l,":",len(hogp[l]),"samples"
    hogpcl=hogpcl+[l]*len(hogp[l])    

# get some random negative images
hogn=[[] for x in range(cfg.numcl)]
hogncl=[]
check=False
numpy.random.seed(3) # to reproduce results
#from scipy.ndimage import zoom
for im in trNegImages: # for each image
    aim=util.myimread(im["name"])
    for idm in range(cfg.numcl):
        szy=(cfg.fy[idm]*2+2)
        szx=(cfg.fx[idm]*2+2)
        rndy=numpy.random.randint(0,aim.shape[0]-szy*8-1)
        rndx=numpy.random.randint(0,aim.shape[1]-szx*8-1)
        #zcim=zoom(crop,(((cfg.fy[idm]*2+2)*8/float(imy)),((cfg.fx[idm]*2+2)*8/float(imx)),1),order=1)
        zcim=aim[rndy:rndy+szy*8,rndx:rndx+szx*8]
        hogn[idm].append(numpy.ascontiguousarray(pyrHOG2.hog(zcim)).flatten())
        #hogncl.append(idm)
        if check:
            print "Aspcet",idm,"HOG",hogn[-1].shape
for l in range(cfg.numcl):  
    print "Aspect",l,":",len(hogn[l]),"samples"
    hogncl=hogncl+[l]*len(hogn[l])    


#################### train a first detector

#empty rigid model
models=[]
for c in range(cfg.numcl):      
    models.append(model.initmodel(cfg.fy[c]*2,cfg.fx[c]*2,1,cfg.useRL,deform=False))

#array with dimensions of w
cumsize=numpy.zeros(numcl+1,dtype=numpy.int)
for idl in range(numcl):
    cumsize[idl+1]=cumsize[idl]+(cfg.fy[idl]*2*cfg.fx[idl]*2)*31+1

try:
    fsf
    models=util.load("%s%d.model"%(testname,0))
    print "Loading Pretrained Initial detector"
except:
    # train detector
    import pegasos
    trpos=[]
    trneg=[]
    for l in range(cfg.numcl):
        trpos+=hogp[l]
        trneg+=hogn[l]

    w,r,prloss=pegasos.trainComp(trpos,trneg,"",hogpcl,hogncl,pc=cfg.svmc,k=1,numthr=1,eps=0.01,bias=bias,notreg=notreg)

    waux=[]
    rr=[]
    w1=numpy.array([])
    #from w to model m1
    for idm,m in enumerate(models):
        models[idm]=model.w2model(w[cumsize[idm]:cumsize[idm+1]-1],-w[cumsize[idm+1]-1]*bias,len(m["ww"]),31,m["ww"][0].shape[0],m["ww"][0].shape[1])
        #models[idm]["ra"]=w[cumsize[idm+1]-1]
        #from model to w #changing the clip...
        waux.append(model.model2w(models[idm],False,False,False))
        rr.append(models[idm]["rho"])
        w1=numpy.concatenate((w1,waux[-1],-numpy.array([models[idm]["rho"]])/bias))
    w2=w
    w=w1

    util.save("%s%d.model"%(testname,0),models)

#show model 
#mm=w[:1860].reshape((cfg.fy[0]*2,cfg.fx[0]*2,31))
it = 0
for idm,m in enumerate(models):   
    import drawHOG
    imm=drawHOG.drawHOG(m["ww"][0])
    pl.figure(100+idm,figsize=(3,3))
    pl.imshow(imm)
    pylab.savefig("%s_hog%d_cl%d.png"%(testname,it,idm))

pl.draw()
pl.show()    

######################### add CRF and rebuild w
for idm,m in enumerate(models):   
    models[idm]["cost"]=0.01*numpy.ones((4,cfg.fy[idm],cfg.fx[idm]))

waux=[]
rr=[]
w1=numpy.array([])
#from w to model m1
for idm,m in enumerate(models):
    waux.append(model.model2w(models[idm],False,False,False,useCRF=True,k=cfg.k))
    rr.append(models[idm]["rho"])
    w1=numpy.concatenate((w1,waux[-1],-numpy.array([models[idm]["rho"]])/bias))
#w2=w #old w
w=w1


#add ids clsize and cumsize for each model
clsize=[]
cumsize=numpy.zeros(numcl+1,dtype=numpy.int)
for l in range(cfg.numcl):
    models[l]["id"]=l
    clsize.append(len(waux[l])+1)
    cumsize[l+1]=cumsize[l]+len(waux[l])+1
clsize=numpy.array(clsize)

lndet=[] #save negative detections
lnfeat=[] #
lnedge=[] #

negratio=[]
negratio2=[]

#from scipy.ndimage import zoom
import detectCRF
from multiprocessing import Pool
import itertools
mypool = Pool(numcore)

####################### repeat scan positives
for it in range(cfg.posit):

    arg=[]
    for idl,l in enumerate(trPosImages):
        bb=l["bbox"]
        for idb,b in enumerate(bb):
            arg.append({"idim":idl,"file":l["name"],"idbb":idb,"bbox":b,"models":models,"cfg":cfg,"flip":False})    

    lpdet=[];lpfeat=[];lpedge=[]
    if not(parallel):
        itr=itertools.imap(detectCRF.refinePos,arg)        
    else:
        itr=mypool.imap(detectCRF.refinePos,arg)

    for ii,res in enumerate(itr):
        if res[0]!=[]:
            if localshow:
                im=myimread(arg[ii]["file"])
                rescale,y1,x1,y2,x2=res[3]
                bb=res[0]["bbox"]
                dy=bb[2]-bb[0]
                dx=bb[3]-bb[1]
                #im=extra.myzoom(im[y1-my:y1+dy+my,x1-mx:x1+dx+mx],(rescale,rescale,1),1)
                im=extra.myzoom(im[y1:y2,x1:x2],(rescale,rescale,1),1)
                detectCRF.visualize2([res[0]],im)
            lpdet.append(res[0])
            lpfeat.append(res[1])
            lpedge.append(res[2])

    #build training data for positives
    trpos=[]
    trposcl=[]
    for idl,l in enumerate(lpdet):#enumerate(lndet):
        trpos.append(numpy.concatenate((lpfeat[idl].flatten(),lpedge[idl].flatten())))
        trposcl.append(l["id"])
 
    ########### repeat scan negatives
    for nit in range(cfg.negit):

        ########### from detections build training data
        
        ltosort=[-x["scr"] for x in lndet]
        lord=numpy.argsort(ltosort)
        trneg=[]
        trnegcl=[]
        print "Total Negative Samples:",len(ltosort)
        print "Negative Support Vectors:",numpy.sum(numpy.array(ltosort)<1)
        print "Kept negative Support Vectors:",cfg.maxexamples

        #filter
        for idl in lord[:cfg.maxexamples]:
            trneg.append(numpy.concatenate((lnfeat[idl].flatten(),lnedge[idl].flatten())))
            trnegcl.append(lndet[idl]["id"])

        #if no negative sample add empty negatives
        for l in range(cfg.numcl):
            if numpy.sum(numpy.array(trnegcl)==l)==0:
                trneg.append(numpy.concatenate((numpy.zeros(models[l]["ww"][0].shape).flatten(),numpy.zeros(models[l]["cost"].shape).flatten())))
                trnegcl.append(l)

        ############ check convergency
        if nit>0: # and not(limit):
            posl,negl,reg,nobj,hpos,hneg=pegasos.objective(trpos,trneg,trposcl,trnegcl,clsize,w,cfg.svmc,cfg.bias,notreg)
            print "NIT:",nit,"OLDLOSS",old_nobj,"NEWLOSS:",nobj
            negratio.append(nobj/(old_nobj+0.000001))
            negratio2.append((posl+negl)/(old_posl+old_negl+0.000001))
            print "RATIO: newobj/oldobj:",negratio,negratio2
            output="Negative not converging yet!"
            #if (negratio[-1]<1.05):
            if (negratio[-1]<cfg.convNeg):
                print "Very small invrement of loss: negative convergence at iteration %d!"%nit
                break

        ############train a new detector with new positive and all negatives
        #print elements per model
        for l in range(cfg.numcl):
            print "Model",l
            print "Positive Examples:",numpy.sum(numpy.array(trposcl)==l)
            print "Negative Examples:",numpy.sum(numpy.array(trnegcl)==l)
    
        import pegasos   
        w,r,prloss=pegasos.trainComp(trpos,trneg,"",trposcl,trnegcl,pc=cfg.svmc,k=numcore*2,numthr=numcore,eps=0.01,bias=cfg.bias,notreg=notreg)

        old_posl,old_negl,old_reg,old_nobj,old_hpos,old_hneg=pegasos.objective(trpos,trneg,trposcl,trnegcl,clsize,w,cfg.svmc,cfg.bias,notreg) 
        waux=[]
        rr=[]
        w1=numpy.array([])
        #from w to model m1
        for idm,m in enumerate(models):
            models[idm]=model.w2model(w[cumsize[idm]:cumsize[idm+1]-1],-w[cumsize[idm+1]-1]*bias,len(m["ww"]),31,m["ww"][0].shape[0],m["ww"][0].shape[1],useCRF=True,k=cfg.k)
            models[idm]["id"]=idm
            #models[idm]["ra"]=w[cumsize[idm+1]-1]
            #from model to w #changing the clip...
            waux.append(model.model2w(models[idm],False,False,False,useCRF=True,k=cfg.k))
            rr.append(models[idm]["rho"])
            w1=numpy.concatenate((w1,waux[-1],-numpy.array([models[idm]["rho"]])/bias))
        w2=w
        w=w1

        util.save("%s%d.model"%(testname,1),models)

        #visualize models
        for idm,m in enumerate(models):   
            import drawHOG
            imm=drawHOG.drawHOG(m["ww"][0])
            pl.figure(100+idm,figsize=(3,3))
            pl.clf()
            pl.imshow(imm)
            pl.title("bias:%.3f |w|^2:%.3f"%(m["rho"],numpy.sum(m["ww"][0]**2)))
            pl.draw()
            pl.show()
            pylab.savefig("%s_hog%d_cl%d.png"%(testname,it,idm))
            #CRF
            pl.figure(120+idm,figsize=(4,4))
            pl.clf()
            extra.showDef(m["cost"])
            pl.draw()
            pl.show()
            pylab.savefig("%s_def%d_cl%d.png"%(testname,it,idm))

        ########### scan negatives
        lndetnew=[];lnfeatnew=[];lnedgenew=[]
        arg=[]
        for idl,l in enumerate(trNegImages):
            #bb=l["bbox"]
            #for idb,b in enumerate(bb):
            arg.append({"idim":idl,"file":l["name"],"idbb":0,"bbox":[],"models":models,"cfg":cfg,"flip":False})    

        if not(parallel):
            itr=itertools.imap(detectCRF.hardNeg,arg)        
        else:
            itr=mypool.imap(detectCRF.hardNeg,arg)

        for ii,res in enumerate(itr):
            if localshow:
                im=myimread(arg[ii]["file"])
                detectCRF.visualize2(res[0],im)
            lndetnew+=res[0]
            lnfeatnew+=res[1]
            lnedgenew+=res[2]
        ########### scan negatives in positives
        
        if cfg.neginpos:
            arg=[]
            for idl,l in enumerate(trPosImages):
                #bb=l["bbox"]
                #for idb,b in enumerate(bb):
                arg.append({"idim":idl,"file":l["name"],"idbb":0,"bbox":l["bbox"],"models":models,"cfg":cfg,"flip":False})    

            lndetnew=[];lnfeatnew=[];lnedgenew=[]
            if not(parallel):
                itr=itertools.imap(detectCRF.hardNegPos,arg)        
            else:
                itr=mypool.imap(detectCRF.hardNegPos,arg)

            for ii,res in enumerate(itr):
                if localshow:
                    im=myimread(arg[ii]["file"])
                    detectCRF.visualize2(res[0],im)
                lndetnew+=res[0]
                lnfeatnew+=res[1]
                lnedgenew+=res[2]

        ########## rescore old detections
        for idl,l in enumerate(lndet):
            idm=l["id"]
            l["scr"]=numpy.sum(models[idm]["ww"][0]*lnfeat[idl])+numpy.sum(models[idm]["cost"]*lnedge[idl])-rr[idm]/bias

        ########### include new detections in the old pool discarding doubles
        #auxdet=[]
        #auxfeat=[]
        #aux=[]
        for newid,newdet in enumerate(lndetnew): # for each newdet
            #newdet=ldetnew[newid]
            remove=False
            for oldid,olddet in enumerate(lndet): # check with the old
                if (newdet["idim"]==olddet["idim"]): #same image
                    if (newdet["scl"]==olddet["scl"]): #same scale
                        if (newdet["id"]==olddet["id"]): #same model
                            if (numpy.all(newdet["def"]==olddet["def"])): #same deformation
                                #same features
                                assert(newdet["scr"]-olddet["scr"]<0.00001)
                                assert(numpy.all(lnfeatnew[newid]-lnfeat[oldid]<0.00001))
                                assert(numpy.all(lnedgenew[newid]==lnedge[oldid]))
                                print "Detection",newdet["idim"],newdet["scl"],newdet["id"],"is double --> removed!"
                                remove=True
            if not(remove):
                lndet.append(lndetnew[newid])
                lnfeat.append(lnfeatnew[newid])
                lnedge.append(lnedgenew[newid])
                
    ##############test
    import denseCRFtest
    #denseCRFtest.runtest(models,tsImages,cfg,parallel=True,numcore=numcore,save="%s%d"%(testname,it),detfun=lambda x :detectCRF.test(x,numhyp=1,show=False),show=localshow)
    denseCRFtest.runtest(models,tsImages,cfg,parallel=True,numcore=numcore,save="%s%d"%(testname,it),show=localshow)


# unitl positve convergercy

