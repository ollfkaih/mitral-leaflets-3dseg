import inspect as ispc
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.optim as optim
import torchmetrics

from utils import LinearCosineLR, MONAI_METRICS



class EnhancedLightningModule(pl.LightningModule):
    def __init__(self, loss=nn.MSELoss(), optimizer={"name": "Adam", "params": {}},
                 lr_scheduler=True, metrics=[]):
        super(EnhancedLightningModule, self).__init__()
        self.loss = loss
        self.optimizer_config = optimizer
        self.lr_scheduler = lr_scheduler
        self._init_metrics(metrics)

    def _init_metrics(self, metrics):
        all_metrics = dict(ispc.getmembers(torchmetrics, ispc.isclass))
        all_metrics.update(MONAI_METRICS)
        # We use `nn.ModuleDict` to always be on proper device and such
        self.metrics = nn.ModuleDict({"mtrain": nn.ModuleDict(),
                                      "mval": nn.ModuleDict(),
                                      "mtest": nn.ModuleDict()})
        def build_metric(name, *args, **kwargs):
            return all_metrics[name](*args, **kwargs)
        for m in metrics:
            for mode in self.metrics.keys():
                if mode == "mtrain" and m["name"] in MONAI_METRICS.keys():
                    # Monai computes with `np.array` so use with parsimony
                    continue
                metric = build_metric(m["name"], *m.get("args", []), **m.get("kwargs", {}))
                display_name = f"v_{m['display_name']}" if mode == "mval" \
                               else m["display_name"]
                self.metrics[mode].update({display_name: metric})


    def _step(self, batch, batch_idx):
        x, y = batch
        #FIXME: Patch for multi-inheritance
        self.preds = self.forward(x)
        errs = self.loss(self.preds, y)
        return errs

    def _update_metrics(self, y, mode="train", log=True):
        # Not sure why but key "train" isn't allowed for an `nn.ModuleDict`
        metrics = self.metrics[f"m{mode}"]
        for m in metrics.values():
            try:
                m(self.preds, y)
            except ValueError as err:
                # Some metrics need int to compute, e.g. Dice
                m(self.preds, y.to(torch.bool))
        #FIXME: Load by steps for test_step
        self.log_dict(metrics, on_epoch=True)

    def _log_errs(self, errs, name="loss", on_step=False):
        if isinstance(errs, dict): # Used in VAE for example
            if 'v' in name:
                errs = {f"v_{k}": v for k, v in errs.items()}
            self.log_dict(errs, prog_bar=True, on_step=on_step, on_epoch=True)
            return errs[name]
        self.log(name, errs, prog_bar=True, on_step=on_step, on_epoch=True)
        return errs if name == "loss" else {"v_loss": errs}


    def training_step(self, batch, batch_idx):
        _, y = batch
        errs = self._step(batch, batch_idx)
        self._update_metrics(y)
        return self._log_errs(errs, on_step=True)

    def validation_step(self, batch, batch_idx):
        _, y = batch
        errs = self._step(batch, batch_idx)
        self._update_metrics(y, "val")
        return self._log_errs(errs, name="v_loss")

    def test_step(self, batch, batch_idx):
        _, y = batch
        errs = self._step(batch, batch_idx)
        self._update_metrics(y, "test")
        return self._log_errs(errs)

    def predict_step(self, batch, batch_idx, dataloader_idx=None):
        errs = self._step(batch, batch_idx)
        return self.preds


    def configure_optimizers(self):
        # All torch optimizer
        optims = dict(ispc.getmembers(optim, ispc.isclass))
        opt = optims[self.optimizer_config.pop("name")](self.parameters(),
                                                        **self.optimizer_config)

        if self.lr_scheduler:
            nb_batches = len(self.trainer._data_connector._train_dataloader_source.dataloader())
            tot_steps = self.trainer.max_epochs * nb_batches
            lr = opt.defaults["lr"]
            lrs = LinearCosineLR(opt, lr, 100, tot_steps)
        return [opt], [{"scheduler": lrs, "interval": "step"}]

    #def configure_callbacks(self):
    #    return pl.callbacks.ModelCheckpoint(monitor="v_loss")
