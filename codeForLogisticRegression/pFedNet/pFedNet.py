import numpy as np 
from optimizerForServer import AlternativeOptimizer
from sklearn.decomposition import PCA 
import cvxpy as cp
from settingsOfpFedNet import FormulationSettings as FormulationSettingsOfpFedNet, PersonalizedModelSettings as PersonalizedModelSettingsOfpFedNet
import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from models import ConvexClustering, ClusterPath, FederatedLogisticRegression
from settings import DataFederation as DataFederationOfpFedNet, FederatedLearningSettings as FederatedLearningSettingsOfpFedNet
from datasets import LngxbhbcdexzlhzcxfxycDataset, IITnbswmbbfxycDataset, Covid19EventPredictionDataset, AkiPredictionDataset
from tools import ModelLogger

class CvxOptimizer(object):
    """
    The cvx optimizer to solve local models (for clients). No global models (for servers).
    """
    def __init__(self, givenDataFederation, givenFormulationSettings, givenFederatedLearningSettings):
        assert(isinstance(givenDataFederation, DataFederationOfpFedNet))
        assert(isinstance(givenFormulationSettings, FormulationSettingsOfpFedNet))
        assert(isinstance(givenFederatedLearningSettings, FederatedLearningSettingsOfpFedNet))
        self.__dataFederation = givenDataFederation
        self.__formulationSettings = givenFormulationSettings
        self.__federatedLearningSettings = givenFederatedLearningSettings
        self.__MMat, self.__NMat, self.__lambda = self.__formulationSettings.getMMat(), self.__formulationSettings.getNMat(), self.__formulationSettings.getLambda()
        self.__QMat = self.__dataFederation.generateQMat()
        self.__sampleMat, self.__labelVec = self.__dataFederation.getDatasetObj().getSampleMat(), self.__dataFederation.getDatasetObj().getLabelVec()
        self.__d1, self.__d2, self.__N = self.__MMat.shape[1], self.__NMat.shape[1], self.__federatedLearningSettings.getNumOfClients()
        self.__x, self.__Z = np.zeros(self.__d1), np.zeros((self.__d2, self.__N)) # sharing, personalized
        self.__personalizedModelVecs = np.einsum('i,j->ij', self.__MMat @ self.__x, np.ones(self.__N)) + self.__NMat @ self.__Z # d by N
        pass
    
    def getPersonalizedModel(self):
        self.__personalizedModelVecs = np.einsum('i,j->ij', self.__MMat @ self.__x, np.ones(self.__N)) + self.__NMat @ self.__Z # d by N
        return self.__personalizedModelVecs

    def updateX(self):
        if self.__d1 == 0: # all features are personalized
            return self.__x 
        x = cp.Variable(len(self.__x))
        Xtn = np.einsum('i,j->ij', self.__MMat @ x, np.ones(self.__d1)) + self.__NMat @ self.__Z
        loss = cp.Minimize( (1.0 / self.__N) * (cp.norm(Xtn - self.__sampleMat, 'fro') ** 2) )
        problem = cp.Problem(loss)
        problem.solve()
        self.__x = x.value
        return 

    def updateZ(self):
        Z = cp.Variable((self.__d2, self.__N)) # personalized models
        if self.__d1 ==0: # all features are personalized
            Xtn = self.__NMat @ Z
        else:
            Xtn = np.einsum('i,j->ij', self.__MMat @ self.__x, np.ones(self.__d1)) + self.__NMat @ Z
        reg = 0
        for columni in range(self.__QMat.shape[1]):
            reg = reg + cp.norm2(Z @ self.__QMat[:,columni])
        flr = FederatedLogisticRegression(givenPersonalizedModels = Xtn, givenSampleMat=self.__sampleMat, givenLabelVec = self.__labelVec, 
                                    givenTrainingSampleIdListOfClient=self.__dataFederation.getSampleIdListOfClient(), givenTestSampleIdListOfClient=self.__dataFederation.getTestSampleIdListOfClient())
        fun =  flr.defineObjectiveFunction()
        loss = cp.Minimize( fun + self.__lambda * reg )
        problem = cp.Problem(loss)
        problem.solve()
        self.__Z = Z.value
    pass

class PersonalizedFederatedLearning(object):
    def __init__(self, givenDataFederation, givenPersonalizedModelSettings, givenFederatedLearningSettings):
        assert(isinstance(givenDataFederation, DataFederationOfpFedNet))
        assert(isinstance(givenPersonalizedModelSettings, PersonalizedModelSettingsOfpFedNet))
        assert(isinstance(givenFederatedLearningSettings, FederatedLearningSettingsOfpFedNet))
        self.__name = 'pFedNet'
        self.__dataFederation = givenDataFederation 
        self.__personalizedModelSettings = givenPersonalizedModelSettings
        self.__federatedLearningSettings = givenFederatedLearningSettings
        self.__formulationSettings = FormulationSettingsOfpFedNet(givenDatasetObj=self.__dataFederation.getDatasetObj(), givenPersonalizedModelSettings = self.__personalizedModelSettings, givenLambda = 5)
        self.__personalizedModelVecs = np.zeros((self.__formulationSettings.getNumberOfFeatures(), self.__federatedLearningSettings.getNumOfClients())) # numberOfFeatures by numberOfClients
        self.__d, self.__N = self.__formulationSettings.getNumberOfFeatures(), self.__federatedLearningSettings.getNumOfClients()
        self.__specificModelObj = self.__initPersonalizedModel(givenName = 'federated logistic regression', givenWarmStart=False)
        self.__loggerPath = self.__initLoggerPath()
        pass
    
    def __initLoggerPath(self):
        if __name__ == '__main__':
            self.__loggerPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "".join(['Lambda=',str(self.__formulationSettings.getLambda())])) 
        else:
            self.__loggerPath = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        return self.__loggerPath
    
    def __initPersonalizedModel(self, givenName, givenWarmStart = True):
        if givenName == 'federated logistic regression':
            pModel = np.zeros((self.__formulationSettings.getNumberOfFeatures(), self.__federatedLearningSettings.getNumOfClients()))
            if givenWarmStart == True:
                pModel = self.__warmStart(givenBasePersonalizedModelFn="xxxxxx")
            specificModel = FederatedLogisticRegression(givenPersonalizedModels = pModel, givenSampleMat = self.__dataFederation.getDatasetObj().getSampleMat(), 
                                                        givenLabelVec = self.__dataFederation.getDatasetObj().getLabelVec(), givenTrainingSampleIdListOfClient = self.__dataFederation.getSampleIdListOfClient(), 
                                                        givenTestSampleIdListOfClient = self.__dataFederation.getTestSampleIdListOfClient())
        return specificModel
    
    def executeBySGD(self):
        ao = AlternativeOptimizer(givenDataFederation=self.__dataFederation, givenFormulationSettings=self.__formulationSettings, 
                                  givenFederatedLearningSettings = self.__federatedLearningSettings, givenSpecificModelObj = self.__specificModelObj)
        for i in range(self.__federatedLearningSettings.getNumOfIterations()):
            self.__specificModelObj.appendRecords()
            # update x
            ao.updateX()
            # update Z
            ao.updateZ()
            # update personalized model
            self.__specificModelObj.updatePersonalziedModels(givenXtn = ao.getPersonalizedModel())
        return 
 
    def executeByCvx(self):
        co = CvxOptimizer(givenDataFederation=self.__dataFederation, givenFormulationSettings=self.__formulationSettings, 
                     givenFederatedLearningSettings=self.__federatedLearningSettings)
        for i in range(self.__federatedLearningSettings.getNumOfIterations()):
            self.__specificModelObj.appendRecords()
            # update x
            co.updateX()
            # update Z
            co.updateZ()
            # update personalized model
            self.__specificModelObj.updatePersonalizedModel(givenPersonalizedModel = co.getPersonalizedModel())
        return 
    
    def logAccuracy(self, givenTypeList = ['training', 'test']):
        self.__initLoggerPath()
        modelLogger = ModelLogger(givenSpecificModel = self.__specificModelObj, givenTargetPath = self.__loggerPath)
        if 'test' in givenTypeList:
            modelLogger.logTestAccuracy(givenDatasetName = self.__dataFederation.getDatasetObj().getName(), 
                                        givenNumOfClients = self.__federatedLearningSettings.getNumOfClients(), givenMethod = self.__name)
        if 'training' in givenTypeList:
            modelLogger.logTrainingAccuracy(givenDatasetName = self.__dataFederation.getDatasetObj().getName(), 
                                            givenNumOfClients = self.__federatedLearningSettings.getNumOfClients(), givenMethod = self.__name)
        pass
    
    def logLoss(self, givenTypeList = ['training', 'test']):
        self.__initLoggerPath()
        modelLogger = ModelLogger(givenSpecificModel = self.__specificModelObj, givenTargetPath = self.__loggerPath)
        if 'test' in givenTypeList:
            modelLogger.logTestLoss(givenDatasetName = self.__dataFederation.getDatasetObj().getName(), 
                                    givenNumOfClients = self.__federatedLearningSettings.getNumOfClients(), givenMethod = self.__name)
        if 'training' in givenTypeList:
            modelLogger.logTrainingLoss(givenDatasetName = self.__dataFederation.getDatasetObj().getName(), 
                                        givenNumOfClients = self.__federatedLearningSettings.getNumOfClients(), givenMethod = self.__name)
        pass

    def logFinalModel(self):
        self.__initLoggerPath()
        modelLogger = ModelLogger(givenSpecificModel = self.__specificModelObj, givenTargetPath = self.__loggerPath)
        modelLogger.logFinalModel(givenDatasetName = self.__dataFederation.getDatasetObj().getName(), givenNumOfClients = self.__federatedLearningSettings.getNumOfClients(), givenMethod = self.__name)
        pass
        
    def getPrincipalComponents(self, givenNumberOfComponents = 2):
        rawModel = self.getPersonalizedModels()
        numOfPersonalizedFeatures = self.__personalizedModelSettings.getNumberOfPersonalizedFeatures()
        personalizedModel = rawModel[-numOfPersonalizedFeatures:,:]
        pca = PCA(n_components=givenNumberOfComponents)
        newModel = pca.fit_transform(personalizedModel.T)
        majorComponent = np.transpose(newModel)
        return majorComponent # numberOfComponents by numberOfSamples

    def getName(self):
        return self.__name
    
    def setLambda(self, givenLambdaVal):
        self.__formulationSettings = FormulationSettingsOfpFedNet(givenDatasetObj=self.__dataFederation.getDatasetObj(), givenPersonalizedModelSettings = self.__personalizedModelSettings, givenLambda = givenLambdaVal)
    pass

class Evaluater(object):
    def __init__(self, givenDatasetObj):
        self.__datasetObj = givenDatasetObj 
        pass
        
    def execute(self):
        federatedLearningSettings = FederatedLearningSettingsOfpFedNet()
        dataFederation = DataFederationOfpFedNet(givenDatasetObj=self.__datasetObj, givenFederatedLearningSettings=federatedLearningSettings)
        personalizedFeatureIdList = list(range(0, self.__datasetObj.getNumberOfFeatures()))
        sharingFeatureIdList=[]
        pcc = PersonalizedFederatedLearning(givenDataFederation=dataFederation, 
                                            givenPersonalizedModelSettings = PersonalizedModelSettingsOfpFedNet(givenFeatureIdListOfPersonalizedComponent=personalizedFeatureIdList, givenFeatureIdListOfSharingComponent=sharingFeatureIdList), 
                                            givenFederatedLearningSettings=federatedLearningSettings)
        pcc.executeBySGD()
        # save test and training accuracy
        pcc.logAccuracy()
        # save test and training loss
        pcc.logLoss()
        # save final model
        pcc.logFinalModel()
        pass

class Dataset(object):
    def __init__(self, givenName):
        self.__name = givenName
        self.__dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
        pass
    
    def get(self):
        if self.__name == 'Lngxbhbcdexzlhzcxfxyc':
            datasetObj = LngxbhbcdexzlhzcxfxycDataset(givenFn = os.path.join(self.__dir, 'data','medicalDatasets','real','classification', 'Lngxbhbcdexzlhzcxfxyc.csv'))
            return datasetObj
        if self.__name == 'IITnbswmbbfxycDataset':
            datasetObj = IITnbswmbbfxycDataset(givenFn = os.path.join(self.__dir, 'data','medicalDatasets','real','classification', '2型糖尿病视网膜病变风险预测.csv'))
            return datasetObj
        if self.__name == 'Covid19EventPrediction': 
            datasetObj = Covid19EventPredictionDataset(givenFn = os.path.join(self.__dir, 'data','medicalDatasets','real','classification', 'Covid19EventPrediction.csv'))
            return datasetObj
        if self.__name == 'AkiPrediction':
            datasetObj = AkiPredictionDataset(givenFn = os.path.join(self.__dir, 'data','medicalDatasets','real','classification', 'AkiPrediction.csv'))
            return datasetObj
        pass
    pass

class TradeoffWrtLambda(object):
    def __init__(self, givenDatasetObj, givenLambdaList):
        self.__datasetObj = givenDatasetObj
        self.__lambdaList = givenLambdaList
        pass
    
    def execute(self):
        federatedLearningSettings = FederatedLearningSettingsOfpFedNet()
        dataFederation = DataFederationOfpFedNet(givenDatasetObj=self.__datasetObj, givenFederatedLearningSettings=federatedLearningSettings)
        personalizedFeatureIdList = list(range(0, self.__datasetObj.getNumberOfFeatures()))
        sharingFeatureIdList=[]
        pcc = PersonalizedFederatedLearning(givenDataFederation=dataFederation, 
                                            givenPersonalizedModelSettings = PersonalizedModelSettingsOfpFedNet(givenFeatureIdListOfPersonalizedComponent=personalizedFeatureIdList, givenFeatureIdListOfSharingComponent=sharingFeatureIdList), 
                                            givenFederatedLearningSettings=federatedLearningSettings)
        for lambdai, lambdav in enumerate(self.__lambdaList):
            print(">>>>>>>>>>>Lambda = {%.5f}<<<<<<<<<<<" % lambdav)
            pcc.setLambda(givenLambdaVal=lambdav)
            pcc.executeBySGD()
            # save test and training accuracy
            pcc.logAccuracy()
        pass
    pass

if __name__ == '__main__':
    np.random.seed(0)
    for datasetName in ['Lngxbhbcdexzlhzcxfxyc', 'IITnbswmbbfxycDataset', 'Covid19EventPrediction']:
        datasetObj = Dataset(givenName=datasetName).get() # 
        TradeoffWrtLambda(givenDatasetObj=datasetObj, givenLambdaList=[1e2, 1e1, 1e0, 1e-1, 1e-2, 1e-3, 1e-4,0]).execute() # 1e2, 1e1, 1e0, 1e-1, 1e-2, 1e-3, 1e-4,0
    pass











